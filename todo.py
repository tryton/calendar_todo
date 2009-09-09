#This file is part of Tryton.  The COPYRIGHT file at the top level of
#this repository contains the full copyright notices and license terms.
from trytond.model import ModelSQL, ModelView, fields
from trytond.tools import Cache, reduce_ids
import uuid
import vobject
import dateutil.tz
tzlocal = dateutil.tz.tzlocal()
tzutc = dateutil.tz.tzutc()
import pytz
import datetime
import xml.dom.minidom
domimpl = xml.dom.minidom.getDOMImplementation()


class Todo(ModelSQL, ModelView):
    "Todo"
    _description = __doc__
    _name = 'calendar.todo'
    _rec_name = 'uuid'

    calendar = fields.Many2One('calendar.calendar', 'Calendar',
            required=True, select=1)
    alarms = fields.One2Many('calendar.todo.alarm', 'todo', 'Alarms')
    classification = fields.Selection([
        ('public', 'Public'),
        ('private', 'Private'),
        ('confidential', 'Confidential'),
        ], 'Classification', required=True)
    completed = fields.DateTime('Completed',
            states={
                'readonly': "(status != 'completed')",
            }, depends=['status'])
    description = fields.Text('Description')
    dtstart = fields.DateTime('Start Date', select=1)
    location = fields.Many2One('calendar.location', 'Location')
    organizer = fields.Char('Organizer', states={
        'required': "bool(attendees) and not bool(parent)",
        }, depends=['attendees', 'parent'])
    attendees = fields.One2Many('calendar.todo.attendee', 'todo',
            'Attendees')
    percent_complete = fields.Integer('Percent complete',
            states={
                'readonly': "(status not in ('needs-action', 'in-process'))",
            }, depends=['status'])
    recurrences = fields.One2Many('calendar.todo', 'parent', 'Recurrences',
            domain=["('uuid', '=', uuid)",
                "('calendar', '=', calendar)"],
            states={
                'invisible': "bool(parent)",
            }, depends=['uuid', 'calendar', 'parent'])
    recurrence = fields.DateTime('Recurrence', select=1, states={
                'invisible': "not bool(parent)",
                }, depends=['parent'])
    sequence = fields.Integer('Sequence')
    parent = fields.Many2One('calendar.todo', 'Parent',
            domain=["('uuid', '=', uuid)",
                "('parent', '=', False)",
                "('calendar', '=', calendar)"],
            ondelete='CASCADE', depends=['uuid', 'calendar'])
    timezone = fields.Selection('timezones', 'Timezone')
    status = fields.Selection([
        ('', ''),
        ('needs-action', 'Needs-Action'),
        ('completed', 'Completed'),
        ('in-process', 'In-Process'),
        ('cancelled', 'Cancelled'),
        ], 'Status', on_change=['status', 'completed', 'percent_complete'])
    summary = fields.Char('Summary')
    uuid = fields.Char('UUID', required=True,
            help='Universally Unique Identifier', select=1)
    due = fields.DateTime('Due Date', select=1)
    categories = fields.Many2Many('calendar.todo-calendar.category',
            'todo', 'category', 'Categories')
    exdates = fields.One2Many('calendar.todo.exdate', 'todo', 'Exception Dates',
            states={
                'invisible': "bool(parent)",
            }, depends=['parent'])
    exrules = fields.One2Many('calendar.todo.exrule', 'todo', 'Exception Rules',
            states={
                'invisible': "bool(parent)",
            }, depends=['parent'])
    rdates = fields.One2Many('calendar.todo.rdate', 'todo', 'Recurrence Dates',
            states={
                'invisible': "bool(parent)",
            }, depends=['parent'])
    rrules = fields.One2Many('calendar.todo.rrule', 'todo', 'Recurrence Rules',
            states={
                'invisible': "bool(parent)",
            }, depends=['parent'])
    calendar_owner = fields.Function('get_calendar_field',
            type='many2one', relation='res.user', string='Owner',
            fnct_search='search_calendar_field')
    calendar_read_users = fields.Function('get_calendar_field',
            type='many2many', relation='res.user', string='Read Users',
            fnct_search='search_calendar_field')
    calendar_write_users = fields.Function('get_calendar_field',
            type='many2many', relation='res.user', string='Write Users',
            fnct_search='search_calendar_field')
    classification_public = fields.Function('get_classification_public',
            type='boolean', string='Classification Public',
            fnct_search='search_classification_public')
    vtodo = fields.Binary('vtodo')

    def __init__(self):
        super(Todo, self).__init__()
        self._sql_constraints = [
            ('uuid_recurrence_uniq', 'UNIQUE(uuid, calendar, recurrence)',
                'UUID and recurrence must be unique in a calendar!'), #XXX should be unique across all componenets
        ]
        self._constraints += [
            ('check_recurrence', 'invalid_recurrence'),
        ]
        self._error_messages.update({
            'invalid_recurrence': 'Recurrence can not be recurrent!',
        })

    def default_uuid(self, cursor, user, context=None):
        return str(uuid.uuid4())

    def default_sequence(self, cursor, user, context=None):
        return 0

    def default_classification(self, cursor, user, context=None):
        return 'public'

    def default_timezone(self, cursor, user, context=None):
        user_obj = self.pool.get('res.user')
        user_ = user_obj.browse(cursor, user, user, context=context)
        return user_.timezone

    def on_change_status(self, cursor, user, ids, vals, context=None):
        res = {}
        if 'status' not in vals:
            return res
        if vals['status'] == 'completed':
            res['percent_complete'] = 100
            if not vals.get('completed'):
                res['completed'] = datetime.datetime.now()

        return res

    def timezones(self, cursor, user, context=None):
        return [(x, x) for x in pytz.common_timezones] + [('', '')]

    def get_calendar_field(self, cursor, user, ids, name, arg, context=None):
        assert name in ('calendar_owner', 'calendar_read_users',
                'calendar_write_users'), 'Invalid name'
        res = {}
        for todo in self.browse(cursor, user, ids, context=context):
            name = name[9:]
            if name in ('read_users', 'write_users'):
                res[todo.id] = [x.id for x in todo.calendar[name]]
            else:
                res[todo.id] = todo.calendar[name].id
        return res

    def search_calendar_field(self, cursor, user, name, args, context=None):
        args2 = []
        i = 0
        while i < len(args):
            field = args[i][0][9:]
            args2.append(tuple(['calendar.' + field] + list(args[i])[1:]))
            i += 1
        return args2

    def get_classification_public(self, cursor, user, ids, name, arg,
            context=None):
        res = {}
        for todo in self.browse(cursor, user, ids, context=context):
            res[todo.id] = False
            if todo.classification == 'public':
                res[todo.id] = True
        return res

    def search_classification_public(self, cursor, user, name, args,
            context=None):
        args2 = []
        i = 0
        while i < len(args):
            if args[i][2]:
                args2.append(('classification', '=', 'public'))
            else:
                args2.append(('classification', '!=', 'public'))
            i += 1
        return args2

    def check_recurrence(self, cursor, user, ids):
        '''
        Check the recurrence is not recurrent.
        '''
        for todo in self.browse(cursor, user, ids):
            if not todo.parent:
                continue
            if todo.rdates \
                    or todo.rrules \
                    or todo.exdates \
                    or todo.exrules \
                    or todo.recurrences:
                return False
        return True

    def create(self, cursor, user, values, context=None):
        calendar_obj = self.pool.get('calendar.calendar')
        collection_obj = self.pool.get('webdav.collection')

        res = super(Todo, self).create(cursor, user, values, context=context)
        todo = self.browse(cursor, user, res, context=context)
        if todo.organizer == todo.calendar.owner.email \
                or (todo.parent \
                and todo.parent.organizer == todo.parent.calendar.owner.email):
            if todo.organizer == todo.calendar.owner.email:
                attendee_emails = [x.email for x in todo.attendees
                        if x.status != 'declined']
            else:
                attendee_emails = [x.email for x in todo.parent.attendees
                        if x.status != 'declined']
            if attendee_emails:
                calendar_ids = calendar_obj.search(cursor, 0, [
                    ('owner.email', 'in', attendee_emails),
                    ], context=context)
                if not todo.recurrence:
                    for calendar_id in calendar_ids:
                        new_id = self.copy(cursor, 0, todo.id, default={
                            'calendar': calendar_id,
                            'recurrences': False,
                            }, context=context)
                        for recurrence in todo.recurrences:
                            self.copy(cursor, 0, recurrence.id, default={
                                'calendar': calendar_id,
                                'parent': new_id,
                                }, context=context)
                else:
                    parent_ids = self.search(cursor, 0, [
                        ('uuid', '=', todo.uuid),
                        ('calendar.owner.email', 'in', attendee_emails),
                        ('id', '!=', todo.id),
                        ('recurrence', '=', False),
                        ], context=context)
                    for parent in self.browse(cursor, 0, parent_ids,
                            context=context):
                        self.copy(cursor, 0, todo.id, default={
                            'calendar': parent.calendar.id,
                            'parent': parent.id,
                            }, context=context)
        # Restart the cache for todo
        collection_obj.todo(cursor.dbname)
        return res

    def _todo2update(self, cursor, user, todo, context=None):
        rdate_obj = self.pool.get('calendar.todo.rdate')
        exdate_obj = self.pool.get('calendar.todo.exdate')
        rrule_obj = self.pool.get('calendar.todo.rrule')
        exrule_obj = self.pool.get('calendar.todo.exrule')

        res = {}
        res['summary'] = todo.summary
        res['description'] = todo.description
        res['dtstart'] = todo.dtstart
        res['percent_complete'] = todo.percent_complete
        res['completed'] = todo.completed
        res['location'] = todo.location.id
        res['status'] = todo.status
        res['organizer'] = todo.organizer
        res['rdates'] = [('delete_all',)]
        for rdate in todo.rdates:
            vals = rdate_obj._date2update(cursor, user, rdate, context=context)
            res['rdates'].append(('create', vals))
        res['exdates'] = [('delete_all',)]
        for exdate in todo.exdates:
            vals = exdate_obj._date2update(cursor, user, exdate, context=context)
            res['exdates'].append(('create', vals))
        res['rrules'] = [('delete_all',)]
        for rrule in todo.rrules:
            vals = rrule_obj._rule2update(cursor, user, rrule, context=context)
            res['rrules'].append(('create', vals))
        res['exrules'] = [('delete_all',)]
        for exrule in todo.exrules:
            vals = exrule_obj._rule2update(cursor, user, exrule, context=context)
            res['exrules'].append(('create', vals))
        return res

    def write(self, cursor, user, ids, values, context=None):
        calendar_obj = self.pool.get('calendar.calendar')
        collection_obj = self.pool.get('webdav.collection')

        values = values.copy()
        if 'sequence' in values:
            del values['sequence']

        res = super(Todo, self).write(cursor, user, ids, values,
                context=context)

        if isinstance(ids, (int, long)):
            ids = [ids]

        for i in range(0, len(ids), cursor.IN_MAX):
            sub_ids = ids[i:i + cursor.IN_MAX]
            red_sql, red_ids = reduce_ids('id', sub_ids)
            cursor.execute('UPDATE "' + self._table + '" ' \
                    'SET sequence = sequence + 1 ' \
                    'WHERE ' + red_sql, red_ids)

        for todo in self.browse(cursor, user, ids, context=context):
            if todo.organizer == todo.calendar.owner.email \
                    or (todo.parent \
                    and todo.parent.organizer == todo.calendar.owner.email):
                if todo.organizer == todo.calendar.owner.email:
                    attendee_emails = [x.email for x in todo.attendees
                            if x.status != 'declined']
                else:
                    attendee_emails = [x.email for x in todo.parent.attendees
                            if x.status != 'declined']
                if attendee_emails:
                    todo_ids = self.search(cursor, 0, [
                        ('uuid', '=', todo.uuid),
                        ('calendar.owner.email', 'in', attendee_emails),
                        ('id', '!=', todo.id),
                        ('recurrence', '=', todo.recurrence or False),
                        ], context=context)
                    for todo2 in self.browse(cursor, user, todo_ids,
                            context=context):
                        if todo2.calendar.owner.email in attendee_emails:
                            attendee_emails.remove(todo2.calendar.owner.email)
                    self.write(cursor, 0, todo_ids, self._todo2update(
                        cursor, user, todo, context=context), context=context)
                if attendee_emails:
                    calendar_ids = calendar_obj.search(cursor, 0, [
                        ('owner.email', 'in', attendee_emails),
                        ], context=context)
                    if not todo.recurrence:
                        for calendar_id in calendar_ids:
                            new_id = self.copy(cursor, 0, todo.id, default={
                                'calendar': calendar_id,
                                'recurrences': False,
                                }, context=context)
                            for recurrence in todo.recurrences:
                                self.copy(cursor, 0, recurrence.id, default={
                                    'calendar': calendar_id,
                                    'parent': new_id,
                                    }, context=context)
                    else:
                        parent_ids = self.search(cursor, 0, [
                            ('uuid', '=', todo.uuid),
                            ('calendar.owner.email', 'in', attendee_emails),
                            ('id', '!=', todo.id),
                            ('recurrence', '=', False),
                            ], context=context)
                        for parent in self.browse(cursor, 0, parent_ids,
                                context=context):
                            self.copy(cursor, 0, todo.id, default={
                                'calendar': parent.calendar.id,
                                'parent': parent.id,
                                }, context=context)
        # Restart the cache for todo
        collection_obj.todo(cursor.dbname)
        return res

    def delete(self, cursor, user, ids, context=None):
        attendee_obj = self.pool.get('calendar.todo.attendee')
        collection_obj = self.pool.get('webdav.collection')

        if isinstance(ids, (int, long)):
            ids = [ids]
        for todo in self.browse(cursor, user, ids, context=context):
            if todo.organizer == todo.calendar.owner.email \
                    or (todo.parent \
                    and todo.parent.organizer == todo.calendar.owner.email):
                if todo.organizer == todo.calendar.owner.email:
                    attendee_emails = [x.email for x in todo.attendees]
                else:
                    attendee_emails = [x.email for x in todo.parent.attendees]
                if attendee_emails:
                    todo_ids = self.search(cursor, 0, [
                        ('uuid', '=', todo.uuid),
                        ('calendar.owner.email', 'in', attendee_emails),
                        ('id', '!=', todo.id),
                        ('recurrence', '=', todo.recurrence or False),
                        ], context=context)
                    self.delete(cursor, 0, todo_ids, context=context)
            elif todo.organizer \
                    or (todo.parent and todo.parent.organizer):
                if todo.organizer:
                    organizer = todo.organizer
                else:
                    organizer = todo.parent.organizer
                todo_ids = self.search(cursor, 0, [
                    ('uuid', '=', todo.uuid),
                    ('calendar.owner.email', '=', organizer),
                    ('id', '!=', todo.id),
                    ('recurrence', '=', todo.recurrence or False),
                    ], context=context, limit=1)
                if todo_ids:
                    todo2 = self.browse(cursor, 0, todo_ids[0],
                            context=context)
                    for attendee in todo2.attendees:
                        if attendee.email == todo.calendar.owner.email:
                            attendee_obj.write(cursor, 0, attendee.id, {
                                'status': 'declined',
                                }, context=context)
        # Restart the cache for todo
        collection_obj.todo(cursor.dbname)
        return super(Todo, self).delete(cursor, user, ids, context=context)

    def ical2values(self, cursor, user, todo_id, ical, calendar_id,
            vtodo=None, context=None):
        '''
        Convert iCalendar to values for create or write

        :param cursor: the database cursor
        :param user: the user id
        :param todo_id: the todo id for write or None for create
        :param ical: a ical instance of vobject
        :param calendar_id: the calendar id of the todo
        :param vtodo: the vtodo of the ical to use if None use the first one
        :param context: the context
        :return: a dictionary with values
        '''
        category_obj = self.pool.get('calendar.category')
        location_obj = self.pool.get('calendar.location')
        user_obj = self.pool.get('res.user')
        alarm_obj = self.pool.get('calendar.todo.alarm')
        attendee_obj = self.pool.get('calendar.todo.attendee')
        rdate_obj = self.pool.get('calendar.todo.rdate')
        exdate_obj = self.pool.get('calendar.todo.exdate')
        rrule_obj = self.pool.get('calendar.todo.rrule')
        exrule_obj = self.pool.get('calendar.todo.exrule')

        vtodos = []
        if not vtodo:
            vtodo = ical.vtodo

            for i in ical.getChildren():
                if i.name == 'VTODO' \
                        and i != vtodo:
                    vtodos.append(i)

        todo = None
        if todo_id:
            todo = self.browse(cursor, user, todo_id, context=context)
        res = {}
        if not todo:
            if hasattr(vtodo, 'uid'):
                res['uuid'] = vtodo.uid.value
            else:
                res['uuid'] = str(uuid.uuid4())
        if hasattr(vtodo, 'summary'):
            res['summary'] = vtodo.summary.value
        else:
            res['summary'] = False
        if hasattr(vtodo, 'description'):
            res['description'] = vtodo.description.value
        else:
            res['description'] = False
        if hasattr(vtodo, 'percent_complete'):
            res['percent_complete'] = int(vtodo.percent_complete.value)
        else:
            res['percent_complete'] = False

        if hasattr(vtodo, 'completed'):
            if not isinstance(vtodo.completed.value, datetime.datetime):
                res['completed'] = datetime.datetime.combine(vtodo.completed.value,
                        datetime.time())
            else:
                if vtodo.completed.value.tzinfo:
                    res['completed'] = vtodo.completed.value.astimezone(tzlocal)
                else:
                    res['completed'] = vtodo.completed.value

        if hasattr(vtodo, 'dtstart'):
            if not isinstance(vtodo.dtstart.value, datetime.datetime):
                res['dtstart'] = datetime.datetime.combine(vtodo.dtstart.value,
                        datetime.time())
            else:
                if vtodo.dtstart.value.tzinfo:
                    res['dtstart'] = vtodo.dtstart.value.astimezone(tzlocal)
                else:
                    res['dtstart'] = vtodo.dtstart.value

        if hasattr(vtodo, 'due'):
            if not isinstance(vtodo.due.value, datetime.datetime):
                res['due'] = datetime.datetime.combine(vtodo.due.value,
                        datetime.time())
            else:
                if vtodo.due.value.tzinfo:
                    res['due'] = vtodo.due.value.astimezone(tzlocal)
                else:
                    res['due'] = vtodo.due.value

        if hasattr(vtodo, 'recurrence-id'):
            if not isinstance(vtodo.recurrence_id.value, datetime.datetime):
                res['recurrence'] = datetime.datetime.combine(
                        vtodo.recurrence_id.value, datetime.time())
            else:
                if vtodo.recurrence_id.value.tzinfo:
                    res['recurrence'] = \
                            vtodo.recurrence_id.value.astimezone(tzlocal)
                else:
                    res['recurrence'] = vtodo.recurrence_id.value
        else:
            res['recurrence'] = False
        if hasattr(vtodo, 'status'):
            res['status'] = vtodo.status.value.lower()
        else:
            res['status'] = ''
        if hasattr(vtodo, 'categories'):
            category_ids = category_obj.search(cursor, user, [
                ('name', 'in', [x for x in vtodo.categories.value]),
                ], context=context)
            categories = category_obj.browse(cursor, user, category_ids,
                    context=context)
            category_names2ids = {}
            for category in categories:
                category_names2ids[category.name] = category.id
            for category in vtodo.categories.value:
                if category not in category_names2ids:
                    category_ids.append(category_obj.create(cursor, user, {
                        'name': category,
                        }, context=context))
            res['categories'] = [('set', category_ids)]
        else:
            res['categories'] = [('unlink_all',)]
        if hasattr(vtodo, 'class'):
            if getattr(vtodo, 'class').value.lower() in \
                    dict(self.classification.selection):
                res['classification'] = getattr(vtodo, 'class').value.lower()
            else:
                res['classification'] = 'public'
        else:
            res['classification'] = 'public'
        if hasattr(vtodo, 'location'):
            location_ids = location_obj.search(cursor, user, [
                ('name', '=', vtodo.location.value),
                ], limit=1, context=context)
            if not location_ids:
                location_id = location_obj.create(cursor, user, {
                    'name': vtodo.location.value,
                    }, context=context)
            else:
                location_id = location_ids[0]
            res['location'] = location_id
        else:
            res['location'] = False

        res['calendar'] = calendar_id

        if hasattr(vtodo, 'organizer'):
            if vtodo.organizer.value.lower().startswith('mailto:'):
                res['organizer'] = vtodo.organizer.value[7:]
            else:
                res['organizer'] = vtodo.organizer.value
        else:
            res['organizer'] = False

        attendees_todel = {}
        if todo:
            for attendee in todo.attendees:
                attendees_todel[attendee.email] = attendee.id
        res['attendees'] = []
        if hasattr(vtodo, 'attendee'):
            while vtodo.attendee_list:
                attendee = vtodo.attendee_list.pop()
                vals = attendee_obj.attendee2values(cursor, user, attendee,
                        context=context)
                if vals['email'] in attendees_todel:
                    res['attendees'].append(('write',
                        attendees_todel[vals['email']], vals))
                    del attendees_todel[vals['email']]
                else:
                    res['attendees'].append(('create', vals))
        res['attendees'].append(('delete', attendees_todel.values()))

        res['rdates'] = []
        if todo:
            res['rdates'].append(('delete', [x.id for x in todo.rdates]))
        if hasattr(vtodo, 'rdate'):
            while vtodo.rdate_list:
                rdate = vtodo.rdate_list.pop()
                for date in rdate.value:
                    vals = rdate_obj.date2values(cursor, user, date,
                            context=context)
                    res['rdates'].append(('create', vals))

        res['exdates'] = []
        if todo:
            res['exdates'].append(('delete', [x.id for x in todo.exdates]))
        if hasattr(vtodo, 'exdate'):
            while vtodo.exdate_list:
                exdate = vtodo.exdate_list.pop()
                for date in exdate.value:
                    vals = exdate_obj.date2values(cursor, user, date,
                            context=context)
                    res['exdates'].append(('create', vals))

        res['rrules'] = []
        if todo:
            res['rrules'].append(('delete', [x.id for x in todo.rrules]))
        if hasattr(vtodo, 'rrule'):
            while vtodo.rrule_list:
                rrule = vtodo.rrule_list.pop()
                vals = rrule_obj.rule2values(cursor, user, rrule,
                        context=context)
                res['rrules'].append(('create', vals))

        res['exrules'] = []
        if todo:
            res['exrules'].append(('delete', [x.id for x in todo.exrules]))
        if hasattr(vtodo, 'exrule'):
            while vtodo.exrule_list:
                exrule = vtodo.exrule_list.pop()
                vals = exrule_obj.rule2values(cursor, user, exrule,
                        context=context)
                res['exrules'].append(('create', vals))

        if todo:
            res.setdefault('alarms', [])
            res['alarms'].append(('delete', [x.id for x in todo.alarms]))
        if hasattr(vtodo, 'valarm'):
            res.setdefault('alarms', [])
            while vtodo.valarm_list:
                valarm = vtodo.valarm_list.pop()
                vals = alarm_obj.valarm2values(cursor, user, valarm,
                        context=context)
                res['alarms'].append(('create', vals))

        if hasattr(ical, 'vtimezone'):
            if ical.vtimezone.tzid.value in pytz.common_timezones:
                res['timezone'] = ical.vtimezone.tzid.value
            else:
                for timezone in pytz.common_timezones:
                    if ical.vtimezone.tzid.value.endswith(timezone):
                        res['timezone'] = timezone

        res['vtodo'] = vtodo.serialize()

        recurrences_todel = []
        if todo:
            recurrences_todel = [x.id for x in todo.recurrences]
        for vtodo in vtodos:
            todo_id = None
            if todo:
                for recurrence in todo.recurrences:
                    if recurrence.recurrence.replace(tzinfo=tzlocal) \
                            == vtodo.recurrence_id.value:
                        todo_id = recurrence.id
                        recurrences_todel.remove(recurrence.id)
            vals = self.ical2values(cursor, user, todo_id, ical,
                    calendar_id, vtodo=vtodo, context=context)
            if todo:
                vals['uuid'] = todo.uuid
            else:
                vals['uuid'] = res['uuid']
            res.setdefault('recurrences', [])
            if todo_id:
                res['recurrences'].append(('write', todo_id, vals))
            else:
                res['recurrences'].append(('create', vals))
        if recurrences_todel:
            res.setdefault('recurrences', [])
            res['recurrences'].append(('delete', recurrences_todel))
        return res

    def todo2ical(self, cursor, user, todo, context=None):
        '''
        Return an iCalendar instance of vobject for todo

        :param cursor: the database cursor
        :param user: the user id
        :param todo: a BrowseRecord of calendar.todo
            or a calendar.todo id
        :param calendar: a BrowseRecord of calendar.calendar
            or a calendar.calendar id
        :param context: the context
        :return: an iCalendar instance of vobject
        '''
        user_obj = self.pool.get('res.user')
        alarm_obj = self.pool.get('calendar.todo.alarm')
        attendee_obj = self.pool.get('calendar.todo.attendee')
        rdate_obj = self.pool.get('calendar.todo.rdate')
        exdate_obj = self.pool.get('calendar.todo.exdate')
        rrule_obj = self.pool.get('calendar.todo.rrule')
        exrule_obj = self.pool.get('calendar.todo.exrule')

        if isinstance(todo, (int, long)):
            todo = self.browse(cursor, user, todo, context=context)

        user_ = user_obj.browse(cursor, user, user, context=context)
        if todo.timezone:
            tztodo = pytz.timezone(todo.timezone)
        elif user_.timezone:
                tztodo = pytz.timezone(user_.timezone)
        else:
            tztodo = tzlocal

        ical = vobject.iCalendar()
        vtodo = ical.add('vtodo')
        if todo.vtodo:
            ical.vtodo = vobject.readOne(todo.vtodo)
            vtodo = ical.vtodo
            ical.vtodo.transformToNative()
        if todo.summary:
            if not hasattr(vtodo, 'summary'):
                vtodo.add('summary')
            vtodo.summary.value = todo.summary
        elif hasattr(vtodo, 'summary'):
            del vtodo.summary
        if todo.percent_complete:
            if not hasattr(vtodo, 'percent-complete'):
                vtodo.add('percent-complete')
            vtodo.percent_complete.value = str(todo.percent_complete)
        elif hasattr(vtodo, 'percent_complete'):
            del vtodo.percent_complete
        if todo.description:
            if not hasattr(vtodo, 'description'):
                vtodo.add('description')
            vtodo.description.value = todo.description
        elif hasattr(vtodo, 'description'):
            del vtodo.description

        if todo.completed:
            if not hasattr(vtodo, 'completed'):
                vtodo.add('completed')
            vtodo.completed.value = todo.completed.replace(tzinfo=tzlocal)\
                    .astimezone(tzutc)
        elif hasattr(vtodo, 'completed'):
            del vtodo.completed

        if todo.dtstart:
            if not hasattr(vtodo, 'dtstart'):
                vtodo.add('dtstart')
            vtodo.dtstart.value = todo.dtstart.replace(tzinfo=tzlocal)\
                    .astimezone(tztodo)
        elif hasattr(vtodo, 'dtstart'):
            del vtodo.dtstart

        if todo.due:
            if not hasattr(vtodo, 'due'):
                vtodo.add('due')
            vtodo.due.value = todo.due.replace(tzinfo=tzlocal)\
                    .astimezone(tztodo)
        elif hasattr(vtodo, 'due'):
            del vtodo.due


        if not hasattr(vtodo, 'created'):
            vtodo.add('created')
        vtodo.created.value = todo.create_date.replace(tzinfo=tzlocal).astimezone(tztodo)
        if not hasattr(vtodo, 'dtstamp'):
            vtodo.add('dtstamp')
        date = todo.write_date or todo.create_date
        vtodo.dtstamp.value = date.replace(tzinfo=tzlocal).astimezone(tztodo)
        if not hasattr(vtodo, 'last-modified'):
            vtodo.add('last-modified')
        vtodo.last_modified.value = date.replace(tzinfo=tzlocal).astimezone(tztodo)
        if todo.recurrence:
            if not hasattr(vtodo, 'recurrence-id'):
                vtodo.add('recurrence-id')
            if todo.all_day:
                vtodo.recurrence_id.value = todo.recurrence.date()
            else:
                vtodo.recurrence_id.value = todo.recurrence\
                        .replace(tzinfo=tzlocal).astimezone(tztodo)
        if todo.status:
            if not hasattr(vtodo, 'status'):
                vtodo.add('status')
            vtodo.status.value = todo.status.upper()
        elif hasattr(vtodo, 'status'):
            del vtodo.status
        if not hasattr(vtodo, 'uid'):
            vtodo.add('uid')
        vtodo.uid.value = todo.uuid
        if not hasattr(vtodo, 'sequence'):
            vtodo.add('sequence')
        vtodo.sequence.value = str(todo.sequence) or '0'
        if todo.categories:
            if not hasattr(vtodo, 'categories'):
                vtodo.add('categories')
            vtodo.categories.value = [x.name for x in todo.categories]
        elif hasattr(vtodo, 'categories'):
            del vtodo.categories
        if not hasattr(vtodo, 'class'):
            vtodo.add('class')
            getattr(vtodo, 'class').value = todo.classification.upper()
        elif getattr(vtodo, 'class').value.lower() in \
                dict(self.classification.selection):
            getattr(vtodo, 'class').value = todo.classification.upper()
        if todo.location:
            if not hasattr(vtodo, 'location'):
                vtodo.add('location')
            vtodo.location.value = todo.location.name
        elif hasattr(vtodo, 'location'):
            del vtodo.location

        if todo.organizer:
            if not hasattr(vtodo, 'organizer'):
                vtodo.add('organizer')
            vtodo.organizer.value = 'MAILTO:' + todo.organizer
        elif hasattr(vtodo, 'organizer'):
            del vtodo.organizer

        vtodo.attendee_list = []
        for attendee in todo.attendees:
            vtodo.attendee_list.append(attendee_obj.attendee2attendee(
                cursor, user, attendee, context=context))

        if todo.rdates:
            vtodo.add('rdate')
            vtodo.rdate.value = []
            for rdate in todo.rdates:
                vtodo.rdate.value.append(rdate_obj.date2date(cursor, user,
                    rdate, context=context))

        if todo.exdates:
            vtodo.add('exdate')
            vtodo.exdate.value = []
            for exdate in todo.exdates:
                vtodo.exdate.value.append(exdate_obj.date2date(cursor, user,
                    exdate, context=context))

        if todo.rrules:
            for rrule in todo.rrules:
                vtodo.add('rrule').value = rrule_obj.rule2rule(cursor, user,
                        rrule, context=context)

        if todo.exrules:
            for exrule in todo.exrules:
                vtodo.add('exrule').value = exrule_obj.rule2rule(cursor, user,
                        exrule, context=context)

        vtodo.valarm_list = []
        for alarm in todo.alarms:
            valarm = alarm_obj.alarm2valarm(cursor, user, alarm,
                    context=context)
            if valarm:
                vtodo.valarm_list.append(valarm)

        for recurrence in todo.recurrences:
            rical = self.todo2ical(cursor, user, recurrence, context=context)
            ical.vtodo_list.append(rical.vtodo)
        return ical

Todo()


class TodoCategory(ModelSQL):
    'Todo - Category'
    _description = __doc__
    _name = 'calendar.todo-calendar.category'

    todo = fields.Many2One('calendar.todo', 'To-Do', ondelete='CASCADE',
            required=True, select=1)
    category = fields.Many2One('calendar.category', 'Category',
            ondelete='CASCADE', required=True, select=1)

TodoCategory()


class TodoRDate(ModelSQL, ModelView):
    'Recurrence Date'
    _description = __doc__
    _name = 'calendar.todo.rdate'
    _inherits = {'calendar.rdate': 'calendar_rdate'}
    _rec_name = 'datetime'

    calendar_rdate = fields.Many2One('calendar.rdate', 'Calendar RDate',
            required=True, ondelete='CASCADE', select=1)
    todo = fields.Many2One('calendar.todo', 'Todo', ondelete='CASCADE',
            select=1, required=True)

    def create(self, cursor, user, values, context=None):
        todo_obj = self.pool.get('calendar.todo')
        if values.get('todo'):
            # Update write_date of todo
            todo_obj.write(cursor, user, values['todo'], {}, context=context)
        return super(TodoRDate, self).create(cursor, user, values,
                context=context)

    def write(self, cursor, user, ids, values, context=None):
        todo_obj = self.pool.get('calendar.todo')
        if isinstance(ids, (int, long)):
            ids = [ids]
        todo_ids = [x.todo.id for x in self.browse(cursor, user, ids,
            context=context)]
        if values.get('todo'):
            todo_ids.append(values['todo'])
        if todo_ids:
            # Update write_date of todo
            todo_obj.write(cursor, user, todo_ids, {}, context=context)
        return super(TodoRDate, self).write(cursor, user, ids, values,
                context=context)

    def delete(self, cursor, user, ids, context=None):
        todo_obj = self.pool.get('calendar.todo')
        rdate_obj = self.pool.get('calendar.rdate')
        if isinstance(ids, (int, long)):
            ids = [ids]
        todo_rdates = self.browse(cursor, user, ids, context=context)
        rdate_ids = [a.calendar_rdate.id for a in todo_rdates]
        todo_ids = [x.todo.id for x in todo_rdates]
        if todo_ids:
            # Update write_date of todo
            todo_obj.write(cursor, user, todo_ids, {}, context=context)
        res = super(TodoRDate, self).delete(cursor, user, ids, context=context)
        if rdate_ids:
            rdate_obj.delete(cursor, user, rdate_ids, context=context)
        return res

    def _date2update(self, cursor, user, date, context=None):
        date_obj = self.pool.get('calendar.rdate')
        return date_obj._date2update(cursor, user, date, context=context)

    def date2values(self, cursor, user, date, context=None):
        date_obj = self.pool.get('calendar.rdate')
        return date_obj.date2values(cursor, user, date, context=context)

    def date2date(self, cursor, user, date, context=None):
        date_obj = self.pool.get('calendar.rdate')
        return date_obj.date2date(cursor, user, date, context=context)

TodoRDate()


class TodoRRule(ModelSQL, ModelView):
    'Recurrence Rule'
    _description = __doc__
    _name = 'calendar.todo.rrule'
    _inherits = {'calendar.rrule': 'calendar_rrule'}
    _rec_name = 'freq'

    calendar_rrule = fields.Many2One('calendar.rrule', 'Calendar RRule',
            required=True, ondelete='CASCADE', select=1)
    todo = fields.Many2One('calendar.todo', 'Todo', ondelete='CASCADE',
            select=1, required=True)

    def create(self, cursor, user, values, context=None):
        todo_obj = self.pool.get('calendar.todo')
        if values.get('todo'):
            # Update write_date of todo
            todo_obj.write(cursor, user, values['todo'], {}, context=context)
        return super(TodoRRule, self).create(cursor, user, values, context=context)

    def write(self, cursor, user, ids, values, context=None):
        todo_obj = self.pool.get('calendar.todo')
        if isinstance(ids, (int, long)):
            ids = [ids]
        todo_ids = [x.todo.id for x in self.browse(cursor, user, ids,
            context=context)]
        if values.get('todo'):
            todo_ids.append(values['todo'])
        if todo_ids:
            # Update write_date of todo
            todo_obj.write(cursor, user, todo_ids, {}, context=context)
        return super(TodoRRule, self).write(cursor, user, ids, values, context=context)

    def delete(self, cursor, user, ids, context=None):
        todo_obj = self.pool.get('calendar.todo')
        rrule_obj = self.pool.get('calendar.rrule')
        if isinstance(ids, (int, long)):
            ids = [ids]
        todo_rrules = self.browse(cursor, user, ids, context=context)
        rrule_ids = [a.calendar_rrule.id for a in todo_rrules]
        todo_ids = [x.todo.id for x in todo_rrules]
        if todo_ids:
            # Update write_date of todo
            todo_obj.write(cursor, user, todo_ids, {}, context=context)
        res = super(TodoRRule, self).delete(cursor, user, ids, context=context)
        if rrule_ids:
            rrule_obj.delete(cursor, user, rrule_ids, context=context)
        return res

    def _rule2update(self, cursor, user, rule, context=None):
        rule_obj = self.pool.get('calendar.rrule')
        return rule_obj._rule2update(cursor, user, rule, context=context)

    def rule2values(self, cursor, user, rule, context=None):
        rule_obj = self.pool.get('calendar.rrule')
        return rule_obj.rule2values(cursor, user, rule, context=context)

    def rule2rule(self, cursor, user, rule, context=None):
        rule_obj = self.pool.get('calendar.rrule')
        return rule_obj.rule2rule(cursor, user, rule, context=context)

TodoRRule()


class TodoExDate(TodoRDate):
    'Exception Date'
    _description = __doc__
    _name = 'calendar.todo.exdate'

TodoExDate()


class TodoExRule(TodoRRule):
    'Exception Rule'
    _description = __doc__
    _name = 'calendar.todo.exrule'

TodoExRule()


class TodoAttendee(ModelSQL, ModelView):
    'Attendee'
    _description = __doc__
    _name = 'calendar.todo.attendee'
    _inherits = {'calendar.attendee': 'calendar_attendee'}

    calendar_attendee = fields.Many2One('calendar.attendee',
            'Calendar Attendee', required=True, ondelete='CASCADE', select=1)
    todo = fields.Many2One('calendar.todo', 'Todo', ondelete='CASCADE',
            required=True, select=1)

    def create(self, cursor, user, values, context=None):
        todo_obj = self.pool.get('calendar.todo')

        if values.get('todo'):
            # Update write_date of todo
            todo_obj.write(cursor, user, values['todo'], {}, context=context)
        res = super(TodoAttendee, self).create(cursor, user, values,
                context=context)
        attendee = self.browse(cursor, user, res, context=context)
        todo = attendee.todo
        if todo.organizer == todo.calendar.owner.email \
                or (todo.parent \
                and todo.parent.organizer == todo.parent.calendar.owner.email):
            if todo.organizer == todo.calendar.owner.email:
                attendee_emails = [x.email for x in todo.attendees]
            else:
                attendee_emails = [x.email for x in todo.parent.attendees]
            if attendee_emails:
                todo_ids = self.search(cursor, 0, [
                    ('todo.uuid', '=', todo.uuid),
                    ('todo.calendar.owner.email', 'in', attendee_emails),
                    ('id', '!=', todo.id),
                    ('todo.recurrence', '=', todo.recurrence or False),
                    ], context=context)
                for todo_id in todo_ids:
                    self.copy(cursor, 0, res, default={
                        'todo': todo_id,
                        }, context=context)
        return res

    def write(self, cursor, user, ids, values, context=None):
        todo_obj = self.pool.get('calendar.todo')

        if isinstance(ids, (int, long)):
            ids = [ids]
        todo_ids = [x.todo.id for x in self.browse(cursor, user, ids,
            context=context)]
        if values.get('todo'):
            todo_ids.append(values['todo'])
        if todo_ids:
            # Update write_date of todo
            todo_obj.write(cursor, user, todo_ids, {}, context=context)

        if 'email' in values:
            values = values.copy()
            del values['email']

        res = super(TodoAttendee, self).write(cursor, user, ids, values,
                context=context)
        attendees = self.browse(cursor, user, ids, context=context)
        for attendee in attendees:
            todo = attendee.todo
            if todo.organizer == todo.calendar.owner.email \
                    or (todo.parent \
                    and todo.parent.organizer == todo.calendar.owner.email):
                if todo.organizer == todo.calendar.owner.email:
                    attendee_emails = [x.email for x in todo.attendees]
                else:
                    attendee_emails = [x.email for x in todo.parent.attendees]
                if attendee_emails:
                    attendee_ids = self.search(cursor, 0, [
                        ('todo.uuid', '=', todo.uuid),
                        ('todo.calendar.owner.email', 'in', attendee_emails),
                        ('id', '!=', attendee.id),
                        ('todo.recurrence', '=', todo.recurrence or False),
                        ('email', '=', attendee.email),
                        ], context=context)
                    self.write(cursor, 0, attendee_ids, self._attendee2update(
                        cursor, user, attendee, context=context), context=context)
        return res

    def delete(self, cursor, user, ids, context=None):
        todo_obj = self.pool.get('calendar.todo')
        attendee_obj = self.pool.get('calendar.attendee')

        if isinstance(ids, (int, long)):
            ids = [ids]
        todo_attendees = self.browse(cursor, user, ids, context=context)
        calendar_attendee_ids = [a.calendar_attendee.id \
                for a in todo_attendees]
        todo_ids = [x.todo.id for x in todo_attendees]
        if todo_ids:
            # Update write_date of todo
            todo_obj.write(cursor, user, todo_ids, {}, context=context)

        for attendee in self.browse(cursor, user, ids, context=context):
            todo = attendee.todo
            if todo.organizer == todo.calendar.owner.email \
                    or (todo.parent \
                    and todo.parent.organizer == todo.calendar.owner.email):
                if todo.organizer == todo.calendar.owner.email:
                    attendee_emails = [x.email for x in todo.attendees]
                else:
                    attendee_emails = [x.email for x in todo.attendees]
                if attendee_emails:
                    attendee_ids = self.search(cursor, 0, [
                        ('todo.uuid', '=', todo.uuid),
                        ('todo.calendar.owner.email', 'in', attendee_emails),
                        ('id', '!=', attendee.id),
                        ('todo.recurrence', '=', todo.recurrence or False),
                        ('email', '=', attendee.email),
                        ], context=context)
                    self.delete(cursor, 0, attendee_ids, context=context)
            elif (todo.organizer \
                    or (todo.parent and todo.parent.organizer)) \
                    and attendee.email == todo.calendar.owner.email:
                if todo.organizer:
                    organizer = todo.organizer
                else:
                    organizer = todo.parent.organizer
                attendee_ids = self.search(cursor, 0, [
                    ('todo.uuid', '=', todo.uuid),
                    ('todo.calendar.owner.email', '=', organizer),
                    ('id', '!=', attendee.id),
                    ('todo.recurrence', '=', todo.recurrence or False),
                    ('email', '=', attendee.email),
                    ], context=context)
                if attendee_ids:
                    self.write(cursor, 0, attendee_ids, {
                        'status': 'declined',
                        }, context=context)
        res = super(TodoAttendee, self).delete(cursor, user, ids, context=context)
        if calendar_attendee_ids:
            attendee_obj.delete(cursor, user, calendar_attendee_ids,
                    context=context)
        return res

    def _attendee2update(self, cursor, user, attendee, context=None):
        attendee_obj = self.pool.get('calendar.attendee')
        return attendee_obj._attendee2update(cursor, user, attendee,
                context=context)

    def attendee2values(self, cursor, user, attendee, context=None):
        attendee_obj = self.pool.get('calendar.attendee')
        return attendee_obj.attendee2values(cursor, user, attendee,
                context=context)

    def attendee2attendee(self, cursor, user, attendee, context=None):
        attendee_obj = self.pool.get('calendar.attendee')
        return attendee_obj.attendee2attendee(cursor, user, attendee,
                context=context)

TodoAttendee()


class TodoAlarm(ModelSQL):
    'Alarm'
    _description = __doc__
    _name = 'calendar.todo.alarm'
    _inherits = {'calendar.alarm': 'calendar_alarm'}

    calendar_alarm = fields.Many2One('calendar.alarm', 'Calendar Alarm',
            required=True, ondelete='CASCADE', select=1)
    todo = fields.Many2One('calendar.todo', 'Todo', ondelete='CASCADE',
            required=True, select=1)

    def create(self, cursor, user, values, context=None):
        todo_obj = self.pool.get('calendar.todo')
        if values.get('todo'):
            # Update write_date of todo
            todo_obj.write(cursor, user, values['todo'], {}, context=context)
        return super(TodoAlarm, self).create(cursor, user, values, context=context)

    def write(self, cursor, user, ids, values, context=None):
        todo_obj = self.pool.get('calendar.todo')
        if isinstance(ids, (int, long)):
            ids = [ids]
        todo_ids = [x.todo.id for x in self.browse(cursor, user, ids,
            context=context)]
        if values.get('todo'):
            todo_ids.append(values['todo'])
        if todo_ids:
            # Update write_date of todo
            todo_obj.write(cursor, user, todo_ids, {}, context=context)
        return super(TodoAlarm, self).write(cursor, user, ids, values,
                context=context)

    def delete(self, cursor, user, ids, context=None):
        todo_obj = self.pool.get('calendar.todo')
        alarm_obj = self.pool.get('calendar.alarm')
        if isinstance(ids, (int, long)):
            ids = [ids]
        todo_alarms = self.browse(cursor, user, ids, context=context)
        alarm_ids = [a.calendar_alarm.id for a in todo_alarms]
        todo_ids = [x.todo.id for x in todo_alarms]
        if todo_ids:
            # Update write_date of todo
            todo_obj.write(cursor, user, todo_ids, {}, context=context)
        res = super(TodoAlarm, self).delete(cursor, user, ids, context=context)
        if alarm_ids:
            alarm_obj.delete(cursor, user, alarm_ids, context=context)
        return res

    def valarm2values(self, cursor, user, alarm, context=None):
        alarm_obj = self.pool.get('calendar.alarm')
        return alarm_obj.valarm2values(cursor, user, alarm, context=context)

    def alarm2valarm(self, cursor, user, alarm, context=None):
        alarm_obj = self.pool.get('calendar.alarm')
        return alarm_obj.alarm2valarm(cursor, user, alarm, context=context)

TodoAlarm()
