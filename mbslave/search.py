import itertools
import urllib2
import psycopg2.extras
from collections import namedtuple
from lxml import etree as ET
from lxml.builder import E
from mbslave.replication import ReplicationHook

Entity = namedtuple('Entity', ['name', 'fields'])
Field = namedtuple('Field', ['name', 'column'])
MultiField = namedtuple('MultiField', ['name', 'column'])


class Schema(object):

    def __init__(self, entities):
        self.entities = entities
        self.entities_by_id = dict((e.name, e) for e in entities)

    def __getitem__(self, name):
        return self.entities_by_id[name]


class Entity(object):

    def __init__(self, name, fields):
        self.name = name
        self.fields = fields

    def iter_single_fields(self, name=None):
        for field in self.fields:
            if isinstance(field, Field):
                if name is not None and field.name != name:
                    continue
                yield field

    def iter_multi_fields(self, name=None):
        for field in self.fields:
            if isinstance(field, MultiField):
                if name is not None and field.name != name:
                    continue
                yield field


class Column(object):

    def __init__(self, name, foreign=None):
        self.name = name
        self.foreign = foreign


class ForeignColumn(Column):

    def __init__(self, table, name, foreign=None, null=False):
        super(ForeignColumn, self).__init__(name, foreign=foreign)
        self.table = table
        self.null = null


schema = Schema([
    Entity('artist', [
        Field('id', Column('gid')),
        Field('disambiguation', Column('comment')),
        Field('name', Column('name', ForeignColumn('artist_name', 'name'))),
        Field('sort_name', Column('sort_name', ForeignColumn('artist_name', 'name'))),
        Field('country', Column('country', ForeignColumn('country', 'name', null=True))),
        Field('country_code', Column('country', ForeignColumn('country', 'iso_code', null=True))),
        Field('gender', Column('gender', ForeignColumn('gender', 'name', null=True))),
        Field('type', Column('type', ForeignColumn('artist_type', 'name', null=True))),
        MultiField('ipi', ForeignColumn('artist_ipi', 'ipi')),
        MultiField('alias', ForeignColumn('artist_alias', 'name', ForeignColumn('artist_name', 'name'))),
    ]),
    Entity('label', [
        Field('id', Column('gid')),
        Field('disambiguation', Column('comment')),
        Field('code', Column('label_code')),
        Field('name', Column('name', ForeignColumn('label_name', 'name'))),
        Field('sort_name', Column('sort_name', ForeignColumn('label_name', 'name'))),
        Field('country', Column('country', ForeignColumn('country', 'name', null=True))),
        Field('country_code', Column('country', ForeignColumn('country', 'iso_code', null=True))),
        Field('type', Column('type', ForeignColumn('label_type', 'name', null=True))),
        MultiField('ipi', ForeignColumn('label_ipi', 'ipi')),
        MultiField('alias', ForeignColumn('label_alias', 'name', ForeignColumn('label_name', 'name'))),
    ]),
    Entity('work', [
        Field('id', Column('gid')),
        Field('disambiguation', Column('comment')),
        Field('name', Column('name', ForeignColumn('work_name', 'name'))),
        Field('type', Column('type', ForeignColumn('work_type', 'name', null=True))),
        MultiField('iswc', ForeignColumn('iswc', 'iswc')),
        MultiField('alias', ForeignColumn('work_alias', 'name', ForeignColumn('work_name', 'name'))),
    ]),
    Entity('release_group', [
        Field('id', Column('gid')),
        Field('disambiguation', Column('comment')),
        Field('name', Column('name', ForeignColumn('release_name', 'name'))),
        Field('type', Column('type', ForeignColumn('release_group_primary_type', 'name', null=True))),
        MultiField('type',
            ForeignColumn('release_group_secondary_type_join', 'secondary_type',
                ForeignColumn('release_group_secondary_type', 'name'))),
        Field('artist', Column('artist_credit', ForeignColumn('artist_credit', 'name', ForeignColumn('artist_name', 'name')))),
    ]),
    Entity('release', [
        Field('id', Column('gid')),
        Field('disambiguation', Column('comment')),
        Field('barcode', Column('barcode')),
        Field('name', Column('name', ForeignColumn('release_name', 'name'))),
        Field('status', Column('status', ForeignColumn('release_status', 'name', null=True))),
        Field('type', Column('release_group', ForeignColumn('release_group', 'type', ForeignColumn('release_group_primary_type', 'name', null=True)))),
        Field('artist', Column('artist_credit', ForeignColumn('artist_credit', 'name', ForeignColumn('artist_name', 'name')))),
        MultiField('catno', ForeignColumn('release_label', 'catalog_number')),
        MultiField('label', ForeignColumn('release_label', 'label', ForeignColumn('label', 'name', ForeignColumn('label_name', 'name')))),
    ]),
    Entity('recording', [
        Field('id', Column('gid')),
        Field('disambiguation', Column('comment')),
        Field('name', Column('name', ForeignColumn('recording_name', 'name'))),
        Field('artist', Column('artist_credit', ForeignColumn('artist_credit', 'name', ForeignColumn('artist_name', 'name')))),
    ]),
])


SQL_SELECT_TPL = "SELECT\n%(columns)s\nFROM\n%(joins)s\nORDER BY %(sort_column)s"


def generate_iter_query(columns, joins, ids=()):
    id_column = columns[0]
    tpl = ["SELECT", "%(columns)s", "FROM", "%(joins)s"]
    if ids:
        tpl.append("WHERE %(id_column)s IN (%(ids)s)")
    tpl.append("ORDER BY %(id_column)s")
    sql_columns = ',\n'.join('  ' + i for i in columns)
    sql_joins = '\n'.join('  ' + i for i in joins)
    sql = "\n".join(tpl) % dict(columns=sql_columns, joins=sql_joins,
                                id_column=id_column, ids=placeholders(ids))
    return sql


def iter_main(db, kind, ids=()):
    entity = schema[kind]
    joins = [kind]
    tables = set([kind])
    columns = ['%s.id' % (kind,)]
    names = []
    for field in entity.iter_single_fields():
        table = kind
        column = field.column
        while column.foreign is not None:
            foreign_table = table + '__' + column.name + '__' + column.foreign.table
            if foreign_table not in tables:
                join = 'LEFT JOIN' if column.foreign.null else 'JOIN'
                joins.append('%(join)s %(parent)s AS %(label)s ON %(label)s.id = %(child)s.%(child_column)s' % dict(
                    join=join, parent=column.foreign.table, child=table, child_column=column.name, label=foreign_table))
                tables.add(foreign_table)
            table = foreign_table
            column = column.foreign
        columns.append('%s.%s' % (table, column.name))
        names.append(field.name)

    query = generate_iter_query(columns, joins, ids)
    #print query

    cursor = db.cursor()
    cursor.execute(query, ids)

    for row in cursor:
        id = row[0]
        fields = [E.field(kind, name='kind')]
        for name, value in zip(names, row[1:]):
            if isinstance(value, str):
                value = value.decode('utf8')
            if value:
                fields.append(E.field(value, name=name))
        yield id, fields


def iter_sub(db, kind, subtable, ids=()):
    entity = schema[kind]
    joins = []
    tables = set()
    columns = []
    names = []
    for field in entity.iter_multi_fields():
        if field.column.table != subtable:
            continue
        last_column = column = field.column
        table = column.table
        while True:
            if last_column is column:
                if table not in tables:
                    joins.append(table)
                    tables.add(table)
                    columns.append('%s.%s' % (table, kind))
            else:
                foreign_table = table + '__' + last_column.name + '__' + column.table
                if foreign_table not in tables:
                    join = 'LEFT JOIN' if column.null else 'JOIN'
                    joins.append('%(join)s %(parent)s AS %(label)s ON %(label)s.id = %(child)s.%(child_column)s' % dict(
                        join=join, parent=column.table, child=table, child_column=last_column.name, label=foreign_table))
                    tables.add(foreign_table)
                table = foreign_table
            if column.foreign is None:
                break
            last_column = column
            column = column.foreign
        columns.append('%s.%s' % (table, column.name))
        names.append(field.name)

    query = generate_iter_query(columns, joins, ids)
    #print query

    cursor = db.cursor()
    cursor.execute(query, ids)

    fields = []
    last_id = None
    for row in cursor:
        id = row[0]
        if last_id != id:
            if fields:
                yield last_id, fields
            last_id = id
            fields = []
        for name, value in zip(names, row[1:]):
            if isinstance(value, str):
                value = value.decode('utf8')
            if value:
                fields.append(E.field(value, name=name))
    if fields:
        yield last_id, fields


def placeholders(ids):
    return ", ".join(["%s" for i in ids])


def grab_next(iter):
    try:
        return iter.next()
    except StopIteration:
        return None


def merge(main, *extra):
    current = map(grab_next, extra)
    for id, fields in main:
        for i, extra_item in enumerate(current):
            if extra_item is not None:
                if extra_item[0] == id:
                    fields.extend(extra_item[1])
                    current[i] = grab_next(extra[i])
        yield E.doc(*fields)


def fetch_entities(db, kind, ids=()):
    sources = [iter_main(db, kind, ids)]
    subtables = set()
    for field in schema[kind].iter_multi_fields():
        if field.column.table not in subtables:
            sources.append(iter_sub(db, kind, field.column.table, ids))
            subtables.add(field.column.table)
    return merge(*sources)


def fetch_artists(db, ids=()):
    return fetch_entities(db, 'artist', ids)


def fetch_labels(db, ids=()):
    return fetch_entities(db, 'label', ids)


def fetch_release_groups(db, ids=()):
    return fetch_entities(db, 'release_group', ids)


def fetch_recordings(db, ids=()):
    return fetch_entities(db, 'recording', ids)


def fetch_releases(db, ids=()):
    return fetch_entities(db, 'release', ids)


def fetch_works(db, ids=()):
    return fetch_entities(db, 'work', ids)


def fetch_all(cfg, db):
    return itertools.chain(
        fetch_works(db) if cfg.solr.index_works else [],
        fetch_recordings(db) if cfg.solr.index_recordings else [],
        fetch_releases(db) if cfg.solr.index_releases else [],
        fetch_release_groups(db) if cfg.solr.index_release_groups else [],
        fetch_artists(db) if cfg.solr.index_artists else [],
        fetch_labels(db) if cfg.solr.index_labels else [])


class SolrReplicationHook(ReplicationHook):

    def __init__(self, cfg, db, schema):
        super(SolrReplicationHook, self).__init__(cfg, db, schema)

    def begin(self, seq):
        self.deleted = {}
        self.added = set()
        self.seq = seq

    def add_update(self, table, id):
        key = table, id
        if key in self.deleted:
            del self.deleted[key]
        self.added.add(key)

    def after_insert(self, table, values):
        if table in ('artist', 'label', 'release', 'release_group', 'recording', 'work'):
            self.add_update(table, values['id'])
        elif table == 'artist_alias':
            self.add_update('artist', values['artist'])
        elif table == 'label_alias':
            self.add_update('label', values['label'])
        elif table == 'work_alias':
            self.add_update('work', values['work'])
        elif table == 'release_label':
            self.add_update('release', values['release'])

    def after_update(self, table, keys, values):
        if table in ('artist', 'label', 'release', 'release_group', 'recording', 'work'):
            id = keys['id']
            self.add_update(table, id)
            if table == 'release_group':
                cursor = self.db.cursor()
                cursor.execute("SELECT id FROM %s.release WHERE release_group = %%s" % (self.schema,), (id,))
                for release_id, in cursor:
                    self.add_update('release', release_id)
            elif table == 'label':
                cursor = self.db.cursor()
                cursor.execute("SELECT release FROM %s.release_label WHERE label = %%s" % (self.schema,), (id,))
                for release_id, in cursor:
                    self.add_update('release', release_id)
        elif table == 'artist_alias':
            self.add_update('artist', values['artist'])
        elif table == 'label_alias':
            self.add_update('label', values['label'])
        elif table == 'work_alias':
            self.add_update('work', values['work'])
        elif table == 'release_label':
            self.add_update('release', values['release'])

    def before_delete(self, table, keys):
        if table in ('artist', 'label', 'release', 'release_group', 'recording', 'work'):
            key = table, keys['id']
            if key in self.added:
                self.added.remove(key)
            cursor = self.db.cursor()
            cursor.execute("SELECT gid FROM %s.%s WHERE id = %%s" % (self.schema, table), (key[1],))
            row = cursor.fetchone()
            if row is not None:
                self.deleted[key] = row[0]
        elif table == 'artist_alias':
            cursor = self.db.cursor()
            cursor.execute("SELECT artist FROM %s.artist_alias WHERE id = %%s" % (self.schema,), (keys['id'],))
            for artist_id, in cursor:
                self.add_update('artist', artist_id)
        elif table == 'label_alias':
            cursor = self.db.cursor()
            cursor.execute("SELECT label FROM %s.label_alias WHERE id = %%s" % (self.schema,), (keys['id'],))
            for label_id, in cursor:
                self.add_update('label', label_id)
        elif table == 'work_alias':
            cursor = self.db.cursor()
            cursor.execute("SELECT work FROM %s.work_alias WHERE id = %%s" % (self.schema,), (keys['id'],))
            for work_id, in cursor:
                self.add_update('work', work_id)
        elif table == 'release_label':
            cursor = self.db.cursor()
            cursor.execute("SELECT release FROM %s.release_label WHERE id = %%s" % (self.schema,), (keys['id'],))
            for release_id, in cursor:
                self.add_update('release', release_id)

    def after_commit(self):
        xml = []
        xml.append('<update>')
        xml.append(ET.tostring(E.deleted(*map(E.id, set(self.deleted.values())))))
        update = {}
        for table, id in self.added:
            update.setdefault(table, set()).add(id)
        xml.append('<add>')
        for table, ids in update.iteritems():
            fetch_func = globals()['fetch_%ss' % table]
            for doc in fetch_func(self.db, ids):
                xml.append(ET.tostring(doc))
        xml.append('</add>')
        xml.append('</update>')
        filename = '/tmp/mb_solr_data_%d.xml' % self.seq
        print ' - Saved Solr update packet to', filename
        f = open(filename, 'w')
        f.writelines(xml)
        f.close()
        req = urllib2.Request(self.cfg.solr.url + '/update', ''.join(xml),
            {'Content-Type': 'application/xml; encoding=UTF-8'})
        print ' - Updated Solr index at', self.cfg.solr.url
        resp = urllib2.urlopen(req)
        the_page = resp.read()

