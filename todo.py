#This file is part of Tryton.  The COPYRIGHT file at the top level of
#this repository contains the full copyright notices and license terms.
import uuid
import vobject
import dateutil.tz
import pytz
import datetime
import xml.dom.minidom
from trytond.model import ModelSQL, ModelView, fields
from trytond.tools import reduce_ids
from trytond.backend import TableHandler
from trytond.pyson import Eval, If, Bool
from trytond.transaction import Transaction
from trytond.pool import Pool

__all__ = ['Todo', 'TodoCategory', 'TodoRDate', 'TodoRRule', 'TodoExDate',
    'TodoExRule', 'TodoAttendee', 'TodoAlarm']

tzlocal = dateutil.tz.tzlocal()
tzutc = dateutil.tz.tzutc()

domimpl = xml.dom.minidom.getDOMImplementation()


class Todo(ModelSQL, ModelView):
    "Todo"
    __name__ = 'calendar.todo'
    _rec_name = 'uuid'
    calendar = fields.Many2One('calendar.calendar', 'Calendar',
            required=True, select=True, ondelete="CASCADE")
    alarms = fields.One2Many('calendar.todo.alarm', 'todo', 'Alarms')
    classification = fields.Selection([
        ('public', 'Public'),
        ('private', 'Private'),
        ('confidential', 'Confidential'),
        ], 'Classification', required=True)
    completed = fields.DateTime('Completed',
        states={
            'readonly': Eval('status') != 'completed',
            }, depends=['status'])
    description = fields.Text('Description')
    dtstart = fields.DateTime('Start Date', select=True)
    location = fields.Many2One('calendar.location', 'Location')
    organizer = fields.Char('Organizer', states={
            'required': If(Bool(Eval('attendees')),
                ~Eval('parent'), False),
            }, depends=['attendees', 'parent'])
    attendees = fields.One2Many('calendar.todo.attendee', 'todo',
            'Attendees')
    percent_complete = fields.Integer('Percent complete', required=True,
        states={
            'readonly': ~Eval('status').in_(['needs-action', 'in-process']),
            }, depends=['status'])
    occurences = fields.One2Many('calendar.todo', 'parent', 'Occurences',
            domain=[
                ('uuid', '=', Eval('uuid')),
                ('calendar', '=', Eval('calendar')),
            ],
            states={
                'invisible': Bool(Eval('parent')),
            }, depends=['uuid', 'calendar', 'parent'])
    recurrence = fields.DateTime('Recurrence', select=True, states={
            'invisible': ~Eval('_parent_parent'),
            'required': Bool(Eval('_parent_parent')),
            }, depends=['parent'])
    sequence = fields.Integer('Sequence', required=True)
    parent = fields.Many2One('calendar.todo', 'Parent',
            domain=[
                ('uuid', '=', Eval('uuid')),
                ('parent', '=', None),
                ('calendar', '=', Eval('calendar'))
            ],
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
            help='Universally Unique Identifier', select=True)
    due = fields.DateTime('Due Date', select=True)
    categories = fields.Many2Many('calendar.todo-calendar.category',
            'todo', 'category', 'Categories')
    exdates = fields.One2Many('calendar.todo.exdate', 'todo',
        'Exception Dates',
        states={
            'invisible': Bool(Eval('parent')),
            }, depends=['parent'])
    exrules = fields.One2Many('calendar.todo.exrule', 'todo',
        'Exception Rules',
        states={
            'invisible': Bool(Eval('parent')),
            }, depends=['parent'])
    rdates = fields.One2Many('calendar.todo.rdate', 'todo', 'Recurrence Dates',
            states={
                'invisible': Bool(Eval('parent')),
            }, depends=['parent'])
    rrules = fields.One2Many('calendar.todo.rrule', 'todo', 'Recurrence Rules',
            states={
                'invisible': Bool(Eval('parent')),
            }, depends=['parent'])
    calendar_owner = fields.Function(fields.Many2One('res.user', 'Owner'),
            'get_calendar_field', searcher='search_calendar_field')
    calendar_read_users = fields.Function(fields.One2Many('res.user', None,
        'Read Users'), 'get_calendar_field', searcher='search_calendar_field')
    calendar_write_users = fields.Function(fields.One2Many('res.user', None,
        'Write Users'), 'get_calendar_field', searcher='search_calendar_field')
    vtodo = fields.Binary('vtodo')

    @classmethod
    def __setup__(cls):
        super(Todo, cls).__setup__()
        cls._sql_constraints = [
            #XXX should be unique across all componenets
            ('uuid_recurrence_uniq', 'UNIQUE(uuid, calendar, recurrence)',
                'UUID and recurrence must be unique in a calendar!'),
            ]
        cls._constraints += [
            ('check_recurrence', 'invalid_recurrence'),
            ]
        cls._error_messages.update({
                'invalid_recurrence': 'Recurrence can not be recurrent!',
                })

    @classmethod
    def __register__(cls, module_name):
        pool = Pool()
        # Migrate from 1.4: remove classification_public
        ModelData = pool.get('ir.model.data')
        Rule = pool.get('ir.rule')
        with Transaction().set_user(0):
            models_data = ModelData.search([
                ('fs_id', '=', 'rule_group_read_todo_line3'),
                ('module', '=', module_name),
                ('inherit', '=', None),
                ], limit=1)
            if models_data:
                model_data, = models_data
                Rule.delete([Rule(model_data.db_id)])
        super(Todo, cls).__register__(module_name)

    @staticmethod
    def default_uuid():
        return str(uuid.uuid4())

    @staticmethod
    def default_sequence():
        return 0

    @staticmethod
    def default_classification():
        return 'public'

    @staticmethod
    def default_timezone():
        User = Pool().get('res.user')
        user = User(Transaction().user)
        return user.timezone

    @staticmethod
    def default_percent_complete():
        return 0

    def on_change_status(self):
        res = {}
        if not getattr(self, 'status', None):
            return res
        if self.status == 'completed':
            res['percent_complete'] = 100
            if not getattr(self, 'completed', None):
                res['completed'] = datetime.datetime.now()

        return res

    @staticmethod
    def timezones():
        return [(x, x) for x in pytz.common_timezones] + [('', '')]

    def get_calendar_field(self, name):
        name = name[9:]
        if name in ('read_users', 'write_users'):
            return [x.id for x in getattr(self.calendar, name)]
        else:
            return getattr(self.calendar, name).id

    @classmethod
    def search_calendar_field(cls, name, clause):
        return [('calendar.' + name[9:],) + tuple(clause[1:])]

    def check_recurrence(self):
        '''
        Check the recurrence is not recurrent.
        '''
        if not self.parent:
            return True
        if (self.rdates
                or self.rrules
                or self.exdates
                or self.exrules
                or self.occurences):
            return False
        return True

    @classmethod
    def create(cls, values):
        pool = Pool()
        Calendar = pool.get('calendar.calendar')
        Collection = pool.get('webdav.collection')

        todo = super(Todo, cls).create(values)
        if (todo.calendar.owner
                and (todo.organizer == todo.calendar.owner.email
                    or (todo.parent
                        and todo.parent.organizer == \
                            todo.parent.calendar.owner.email))):
            if todo.organizer == todo.calendar.owner.email:
                attendee_emails = [x.email for x in todo.attendees
                        if x.status != 'declined'
                        and x.email != todo.organizer]
            else:
                attendee_emails = [x.email for x in todo.parent.attendees
                        if x.status != 'declined'
                        and x.email != todo.parent.organizer]
            if attendee_emails:
                with Transaction().set_user(0):
                    calendars = Calendar.search([
                        ('owner.email', 'in', attendee_emails),
                        ])
                    if not todo.recurrence:
                        for calendar in calendars:
                            new_todo = cls.copy([todo], default={
                                'calendar': calendar.id,
                                'occurences': None,
                                })
                            for occurence in todo.occurences:
                                cls.copy([occurence], default={
                                    'calendar': calendar.id,
                                    'parent': new_todo.id,
                                    })
                    else:
                        parents = cls.search([
                            ('uuid', '=', todo.uuid),
                            ('calendar.owner.email', 'in', attendee_emails),
                            ('id', '!=', todo.id),
                            ('recurrence', '=', None),
                            ])
                        for parent in parents:
                            cls.copy([todo], default={
                                'calendar': parent.calendar.id,
                                'parent': parent.id,
                                })
        # Restart the cache for todo
        Collection._todo_cache.clear()
        return todo

    def _todo2update(self):
        res = {}
        res['summary'] = self.summary
        res['description'] = self.description
        res['dtstart'] = self.dtstart
        res['percent_complete'] = self.percent_complete
        res['completed'] = self.completed
        res['location'] = self.location.id
        res['status'] = self.status
        res['organizer'] = self.organizer
        res['rdates'] = [('delete_all',)]
        for rdate in self.rdates:
            vals = rdate._date2update()
            res['rdates'].append(('create', vals))
        res['exdates'] = [('delete_all',)]
        for exdate in self.exdates:
            vals = exdate._date2update()
            res['exdates'].append(('create', vals))
        res['rrules'] = [('delete_all',)]
        for rrule in self.rrules:
            vals = rrule._rule2update()
            res['rrules'].append(('create', vals))
        res['exrules'] = [('delete_all',)]
        for exrule in self.exrules:
            vals = exrule._rule2update()
            res['exrules'].append(('create', vals))
        return res

    @classmethod
    def write(cls, todos, values):
        pool = Pool()
        Calendar = pool.get('calendar.calendar')
        Collection = pool.get('webdav.collection')

        cursor = Transaction().cursor

        values = values.copy()
        if 'sequence' in values:
            del values['sequence']

        super(Todo, cls).write(todos, values)

        ids = [t.id for t in todos]
        for i in range(0, len(ids), cursor.IN_MAX):
            sub_ids = ids[i:i + cursor.IN_MAX]
            red_sql, red_ids = reduce_ids('id', sub_ids)
            cursor.execute('UPDATE "' + cls._table + '" ' \
                    'SET sequence = sequence + 1 ' \
                    'WHERE ' + red_sql, red_ids)

        for todo in todos:
            if todo.calendar.owner \
                    and (todo.organizer == todo.calendar.owner.email \
                    or (todo.parent \
                    and todo.parent.organizer == todo.calendar.owner.email)):
                if todo.organizer == todo.calendar.owner.email:
                    attendee_emails = [x.email for x in todo.attendees
                            if x.status != 'declined'
                            and x.email != todo.organizer]
                else:
                    attendee_emails = [x.email for x in todo.parent.attendees
                            if x.status != 'declined'
                            and x.email != todo.parent.organizer]
                if attendee_emails:
                    with Transaction().set_user(0):
                        todo2s = cls.search([
                            ('uuid', '=', todo.uuid),
                            ('calendar.owner.email', 'in', attendee_emails),
                            ('id', '!=', todo.id),
                            ('recurrence', '=', todo.recurrence),
                            ])
                    for todo2 in todo2s:
                        if todo2.calendar.owner.email in attendee_emails:
                            attendee_emails.remove(todo2.calendar.owner.email)
                    with Transaction().set_user(0):
                        cls.write(todos, todo._todo2update())
                if attendee_emails:
                    with Transaction().set_user(0):
                        calendars = Calendar.search([
                            ('owner.email', 'in', attendee_emails),
                            ])
                        if not todo.recurrence:
                            for calendar in calendars:
                                new_todo, = cls.copy([todo], default={
                                    'calendar': calendar.id,
                                    'occurences': None,
                                    })
                                for occurence in todo.occurences:
                                    cls.copy([occurence], default={
                                        'calendar': calendar.id,
                                        'parent': new_todo.id,
                                        })
                        else:
                            parents = cls.search([
                                    ('uuid', '=', todo.uuid),
                                    ('calendar.owner.email', 'in',
                                        attendee_emails),
                                    ('id', '!=', todo.id),
                                    ('recurrence', '=', None),
                                    ])
                            for parent in parents:
                                cls.copy([todo], default={
                                    'calendar': parent.calendar.id,
                                    'parent': parent.id,
                                    })
        # Restart the cache for todo
        Collection._todo_cache.clear()

    @classmethod
    def delete(cls, todos):
        pool = Pool()
        Attendee = pool.get('calendar.todo.attendee')
        Collection = pool.get('webdav.collection')

        for todo in todos:
            if todo.calendar.owner \
                    and (todo.organizer == todo.calendar.owner.email \
                    or (todo.parent \
                    and todo.parent.organizer == todo.calendar.owner.email)):
                if todo.organizer == todo.calendar.owner.email:
                    attendee_emails = [x.email for x in todo.attendees
                            if x.email != todo.organizer]
                else:
                    attendee_emails = [x.email for x in todo.parent.attendees
                            if x.email != todo.parent.organizer]
                if attendee_emails:
                    with Transaction().set_user(0):
                        todos_delete = cls.search([
                            ('uuid', '=', todo.uuid),
                            ('calendar.owner.email', 'in', attendee_emails),
                            ('id', '!=', todo.id),
                            ('recurrence', '=', todo.recurrence),
                            ])
                        cls.delete(todos_delete)
            elif todo.organizer \
                    or (todo.parent and todo.parent.organizer):
                if todo.organizer:
                    organizer = todo.organizer
                else:
                    organizer = todo.parent.organizer
                with Transaction().set_user(0):
                    todo2s = cls.search([
                        ('uuid', '=', todo.uuid),
                        ('calendar.owner.email', '=', organizer),
                        ('id', '!=', todo.id),
                        ('recurrence', '=', todo.recurrence),
                        ], limit=1)
                    if todo2s:
                        todo2, = todo2s
                        for attendee in todo2.attendees:
                            if attendee.email == todo.calendar.owner.email:
                                Attendee.write([attendee], {
                                    'status': 'declined',
                                    })
        super(Todo, cls).delete(todos)
        # Restart the cache for todo
        Collection._todo_cache.clear()

    @classmethod
    def copy(cls, todos, default=None):
        if default is None:
            default = {}

        new_todos = []
        for todo in todos:
            current_default = default.copy()
            current_default['uuid'] = cls.default_uuid()
            new_todo, = super(Todo, cls).copy([todo], default=current_default)
            new_todos.append(new_todo)
        return new_todos

    @classmethod
    def ical2values(cls, todo_id, ical, calendar_id, vtodo=None):
        '''
        Convert iCalendar to values for create or write with:
        todo_id: the todo id for write or None for create
        ical: a ical instance of vobject
        calendar_id: the calendar id of the todo
        vtodo: the vtodo of the ical to use if None use the first one
        '''
        pool = Pool()
        Category = pool.get('calendar.category')
        Location = pool.get('calendar.location')
        Alarm = pool.get('calendar.todo.alarm')
        Attendee = pool.get('calendar.todo.attendee')
        Rdate = pool.get('calendar.todo.rdate')
        Exdate = pool.get('calendar.todo.exdate')
        Rrule = pool.get('calendar.todo.rrule')
        Exrule = pool.get('calendar.todo.exrule')

        vtodos = []
        if not vtodo:
            vtodo = ical.vtodo

            for i in ical.getChildren():
                if i.name == 'VTODO' \
                        and i != vtodo:
                    vtodos.append(i)

        todo = None
        if todo_id:
            todo = cls(todo_id)
        res = {}
        if not todo:
            if hasattr(vtodo, 'uid'):
                res['uuid'] = vtodo.uid.value
            else:
                res['uuid'] = str(uuid.uuid4())
        if hasattr(vtodo, 'summary'):
            res['summary'] = vtodo.summary.value
        else:
            res['summary'] = None
        if hasattr(vtodo, 'description'):
            res['description'] = vtodo.description.value
        else:
            res['description'] = None
        if hasattr(vtodo, 'percent_complete'):
            res['percent_complete'] = int(vtodo.percent_complete.value)
        else:
            res['percent_complete'] = None

        if hasattr(vtodo, 'completed'):
            if not isinstance(vtodo.completed.value, datetime.datetime):
                res['completed'] = datetime.datetime.combine(
                    vtodo.completed.value, datetime.time())
            else:
                if vtodo.completed.value.tzinfo:
                    res['completed'] = vtodo.completed.value.astimezone(
                        tzlocal)
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
            res['recurrence'] = None
        if hasattr(vtodo, 'status'):
            res['status'] = vtodo.status.value.lower()
        else:
            res['status'] = ''
        if hasattr(vtodo, 'categories'):
            categories = Category.search([
                ('name', 'in', [x for x in vtodo.categories.value]),
                ])
            category_names2ids = {}
            for category in categories:
                category_names2ids[category.name] = category.id
            for category in vtodo.categories.value:
                if category not in category_names2ids:
                    categories.append(Category.create({
                        'name': category,
                        }))
            res['categories'] = [('set', [c.id for c in categories])]
        else:
            res['categories'] = [('unlink_all',)]
        if hasattr(vtodo, 'class'):
            if getattr(vtodo, 'class').value.lower() in \
                    dict(cls.classification.selection):
                res['classification'] = getattr(vtodo, 'class').value.lower()
            else:
                res['classification'] = 'public'
        else:
            res['classification'] = 'public'
        if hasattr(vtodo, 'location'):
            locations = Location.search([
                ('name', '=', vtodo.location.value),
                ], limit=1)
            if not locations:
                location, = Location.create({
                    'name': vtodo.location.value,
                    })
            else:
                location, = locations
            res['location'] = location.id
        else:
            res['location'] = None

        res['calendar'] = calendar_id

        if hasattr(vtodo, 'organizer'):
            if vtodo.organizer.value.lower().startswith('mailto:'):
                res['organizer'] = vtodo.organizer.value[7:]
            else:
                res['organizer'] = vtodo.organizer.value
        else:
            res['organizer'] = None

        attendees_todel = {}
        if todo:
            for attendee in todo.attendees:
                attendees_todel[attendee.email] = attendee.id
        res['attendees'] = []
        if hasattr(vtodo, 'attendee'):
            while vtodo.attendee_list:
                attendee = vtodo.attendee_list.pop()
                vals = Attendee.attendee2values(attendee)
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
                    vals = Rdate.date2values(date)
                    res['rdates'].append(('create', vals))

        res['exdates'] = []
        if todo:
            res['exdates'].append(('delete', [x.id for x in todo.exdates]))
        if hasattr(vtodo, 'exdate'):
            while vtodo.exdate_list:
                exdate = vtodo.exdate_list.pop()
                for date in exdate.value:
                    vals = Exdate.date2values(date)
                    res['exdates'].append(('create', vals))

        res['rrules'] = []
        if todo:
            res['rrules'].append(('delete', [x.id for x in todo.rrules]))
        if hasattr(vtodo, 'rrule'):
            while vtodo.rrule_list:
                rrule = vtodo.rrule_list.pop()
                vals = Rrule.rule2values(rrule)
                res['rrules'].append(('create', vals))

        res['exrules'] = []
        if todo:
            res['exrules'].append(('delete', [x.id for x in todo.exrules]))
        if hasattr(vtodo, 'exrule'):
            while vtodo.exrule_list:
                exrule = vtodo.exrule_list.pop()
                vals = Exrule.rule2values(exrule)
                res['exrules'].append(('create', vals))

        if todo:
            res.setdefault('alarms', [])
            res['alarms'].append(('delete', [x.id for x in todo.alarms]))
        if hasattr(vtodo, 'valarm'):
            res.setdefault('alarms', [])
            while vtodo.valarm_list:
                valarm = vtodo.valarm_list.pop()
                vals = Alarm.valarm2values(valarm)
                res['alarms'].append(('create', vals))

        if hasattr(ical, 'vtimezone'):
            if ical.vtimezone.tzid.value in pytz.common_timezones:
                res['timezone'] = ical.vtimezone.tzid.value
            else:
                for timezone in pytz.common_timezones:
                    if ical.vtimezone.tzid.value.endswith(timezone):
                        res['timezone'] = timezone

        res['vtodo'] = vtodo.serialize()

        occurences_todel = []
        if todo:
            occurences_todel = [x.id for x in todo.occurences]
        for vtodo in vtodos:
            todo_id = None
            if todo:
                for occurence in todo.occurences:
                    if occurence.recurrence.replace(tzinfo=tzlocal) \
                            == vtodo.recurrence_id.value:
                        todo_id = occurence.id
                        occurences_todel.remove(occurence.id)
            vals = cls.ical2values(todo_id, ical, calendar_id, vtodo=vtodo)
            if todo:
                vals['uuid'] = todo.uuid
            else:
                vals['uuid'] = res['uuid']
            res.setdefault('occurences', [])
            if todo_id:
                res['occurences'].append(('write', todo_id, vals))
            else:
                res['occurences'].append(('create', vals))
        if occurences_todel:
            res.setdefault('occurences', [])
            res['occurences'].append(('delete', occurences_todel))
        return res

    def todo2ical(self):
        '''
        Return an iCalendar instance of vobject for todo
        '''
        pool = Pool()
        User = pool.get('res.user')

        user = User(Transaction().user)
        if self.timezone:
            tztodo = dateutil.tz.gettz(self.timezone)
        elif user.timezone:
            tztodo = dateutil.tz.gettz(user.timezone)
        else:
            tztodo = tzlocal

        ical = vobject.iCalendar()
        vtodo = ical.add('vtodo')
        if self.vtodo:
            ical.vtodo = vobject.readOne(str(self.vtodo))
            vtodo = ical.vtodo
            ical.vtodo.transformToNative()
        if self.summary:
            if not hasattr(vtodo, 'summary'):
                vtodo.add('summary')
            vtodo.summary.value = self.summary
        elif hasattr(vtodo, 'summary'):
            del vtodo.summary
        if self.percent_complete:
            if not hasattr(vtodo, 'percent-complete'):
                vtodo.add('percent-complete')
            vtodo.percent_complete.value = str(self.percent_complete)
        elif hasattr(vtodo, 'percent_complete'):
            del vtodo.percent_complete
        if self.description:
            if not hasattr(vtodo, 'description'):
                vtodo.add('description')
            vtodo.description.value = self.description
        elif hasattr(vtodo, 'description'):
            del vtodo.description

        if self.completed:
            if not hasattr(vtodo, 'completed'):
                vtodo.add('completed')
            vtodo.completed.value = self.completed.replace(tzinfo=tzlocal)\
                    .astimezone(tzutc)
        elif hasattr(vtodo, 'completed'):
            del vtodo.completed

        if self.dtstart:
            if not hasattr(vtodo, 'dtstart'):
                vtodo.add('dtstart')
            vtodo.dtstart.value = self.dtstart.replace(tzinfo=tzlocal)\
                    .astimezone(tztodo)
        elif hasattr(vtodo, 'dtstart'):
            del vtodo.dtstart

        if self.due:
            if not hasattr(vtodo, 'due'):
                vtodo.add('due')
            vtodo.due.value = self.due.replace(tzinfo=tzlocal)\
                    .astimezone(tztodo)
        elif hasattr(vtodo, 'due'):
            del vtodo.due

        if not hasattr(vtodo, 'created'):
            vtodo.add('created')
        vtodo.created.value = self.create_date.replace(
            tzinfo=tzlocal).astimezone(tztodo)
        if not hasattr(vtodo, 'dtstamp'):
            vtodo.add('dtstamp')
        date = self.write_date or self.create_date
        vtodo.dtstamp.value = date.replace(tzinfo=tzlocal).astimezone(tztodo)
        if not hasattr(vtodo, 'last-modified'):
            vtodo.add('last-modified')
        vtodo.last_modified.value = date.replace(
            tzinfo=tzlocal).astimezone(tztodo)
        if self.recurrence and self.parent:
            if not hasattr(vtodo, 'recurrence-id'):
                vtodo.add('recurrence-id')
            vtodo.recurrence_id.value = self.recurrence\
                    .replace(tzinfo=tzlocal).astimezone(tztodo)
        elif hasattr(vtodo, 'recurrence-id'):
            del vtodo.recurrence_id
        if self.status:
            if not hasattr(vtodo, 'status'):
                vtodo.add('status')
            vtodo.status.value = self.status.upper()
        elif hasattr(vtodo, 'status'):
            del vtodo.status
        if not hasattr(vtodo, 'uid'):
            vtodo.add('uid')
        vtodo.uid.value = self.uuid
        if not hasattr(vtodo, 'sequence'):
            vtodo.add('sequence')
        vtodo.sequence.value = str(self.sequence) or '0'
        if self.categories:
            if not hasattr(vtodo, 'categories'):
                vtodo.add('categories')
            vtodo.categories.value = [x.name for x in self.categories]
        elif hasattr(vtodo, 'categories'):
            del vtodo.categories
        if not hasattr(vtodo, 'class'):
            vtodo.add('class')
            getattr(vtodo, 'class').value = self.classification.upper()
        elif getattr(vtodo, 'class').value.lower() in \
                dict(self.classification.selection):
            getattr(vtodo, 'class').value = self.classification.upper()
        if self.location:
            if not hasattr(vtodo, 'location'):
                vtodo.add('location')
            vtodo.location.value = self.location.name
        elif hasattr(vtodo, 'location'):
            del vtodo.location

        if self.organizer:
            if not hasattr(vtodo, 'organizer'):
                vtodo.add('organizer')
            vtodo.organizer.value = 'MAILTO:' + self.organizer
        elif hasattr(vtodo, 'organizer'):
            del vtodo.organizer

        vtodo.attendee_list = []
        for attendee in self.attendees:
            vtodo.attendee_list.append(attendee.attendee2attendee())

        if self.rdates:
            vtodo.add('rdate')
            vtodo.rdate.value = []
            for rdate in self.rdates:
                vtodo.rdate.value.append(rdate.date2date())

        if self.exdates:
            vtodo.add('exdate')
            vtodo.exdate.value = []
            for exdate in self.exdates:
                vtodo.exdate.value.append(exdate.date2date())

        if self.rrules:
            for rrule in self.rrules:
                vtodo.add('rrule').value = rrule.rule2rule()

        if self.exrules:
            for exrule in self.exrules:
                vtodo.add('exrule').value = exrule.rule2rule()

        vtodo.valarm_list = []
        for alarm in self.alarms:
            valarm = alarm.alarm2valarm()
            if valarm:
                vtodo.valarm_list.append(valarm)

        for occurence in self.occurences:
            rical = self.todo2ical(occurence)
            ical.vtodo_list.append(rical.vtodo)
        return ical


class TodoCategory(ModelSQL):
    'Todo - Category'
    __name__ = 'calendar.todo-calendar.category'
    todo = fields.Many2One('calendar.todo', 'To-Do', ondelete='CASCADE',
            required=True, select=True)
    category = fields.Many2One('calendar.category', 'Category',
            ondelete='CASCADE', required=True, select=True)


class TodoRDate(ModelSQL, ModelView):
    'Todo Recurrence Date'
    __name__ = 'calendar.todo.rdate'
    _inherits = {'calendar.date': 'calendar_date'}
    _rec_name = 'datetime'
    calendar_date = fields.Many2One('calendar.date', 'Calendar Date',
            required=True, ondelete='CASCADE', select=True)
    todo = fields.Many2One('calendar.todo', 'Todo', ondelete='CASCADE',
            select=True, required=True)

    @classmethod
    def __register__(cls, module_name):
        cursor = Transaction().cursor
        # Migration from 1.4: calendar_rdate renamed to calendar_date
        table = TableHandler(cursor, cls, module_name)
        old_column = 'calendar_rdate'
        if table.column_exist(old_column):
            table.column_rename(old_column, 'calendar_date')

        super(TodoRDate, cls).__register__(module_name)

    @classmethod
    def create(cls, values):
        Todo = Pool().get('calendar.todo')
        if values.get('todo'):
            # Update write_date of todo
            Todo.write([Todo(values['todo'])], {})
        return super(TodoRDate, cls).create(values)

    @classmethod
    def write(cls, rdates, values):
        Todo = Pool().get('calendar.todo')
        todos = [x.todo for x in rdates]
        if values.get('todo'):
            todos.append(Todo(values['todo']))
        if todos:
            # Update write_date of todo
            Todo.write(todos, {})
        super(TodoRDate, cls).write(rdates, values)

    @classmethod
    def delete(cls, todo_rdates):
        pool = Pool()
        Todo = pool.get('calendar.todo')
        Rdate = pool.get('calendar.date')
        rdates = [a.calendar_date for a in todo_rdates]
        todos = [x.todo for x in todo_rdates]
        if todos:
            # Update write_date of todo
            Todo.write(todos, {})
        super(TodoRDate, cls).delete(todo_rdates)
        if rdates:
            Rdate.delete(rdates)

    def _date2update(self):
        return self.calendar_date._date2update()

    @classmethod
    def date2values(cls, date):
        Date = Pool().get('calendar.date')
        return Date.date2values(date.calendar_date)

    @classmethod
    def date2date(cls, date):
        Date = Pool().get('calendar.date')
        return Date.date2date(date.calendar_date)


class TodoRRule(ModelSQL, ModelView):
    'Recurrence Rule'
    __name__ = 'calendar.todo.rrule'
    _inherits = {'calendar.rrule': 'calendar_rrule'}
    _rec_name = 'freq'
    calendar_rrule = fields.Many2One('calendar.rrule', 'Calendar RRule',
            required=True, ondelete='CASCADE', select=True)
    todo = fields.Many2One('calendar.todo', 'Todo', ondelete='CASCADE',
            select=True, required=True)

    @classmethod
    def create(cls, values):
        Todo = Pool().get('calendar.todo')
        if values.get('todo'):
            # Update write_date of todo
            Todo.write([Todo(values['todo'])], {})
        return super(TodoRRule, cls).create(values)

    @classmethod
    def write(cls, todo_rrules, values):
        Todo = Pool().get('calendar.todo')
        todos = [x.todo for x in todo_rrules]
        if values.get('todo'):
            todos.append(Todo(values['todo']))
        if todos:
            # Update write_date of todo
            Todo.write(todos, {})
        super(TodoRRule, cls).write(todo_rrules, values)

    @classmethod
    def delete(cls, todo_rrules):
        pool = Pool()
        Todo = pool.get('calendar.todo')
        Rrule = pool.get('calendar.rrule')
        rrules = [a.calendar_rrule for a in todo_rrules]
        todos = [x.todo for x in todo_rrules]
        if todos:
            # Update write_date of todo
            Todo.write(todos, {})
        super(TodoRRule, cls).delete(todo_rrules)
        if rrules:
            Rrule.delete(rrules)

    def _rule2update(self):
        return self.calendar_rrule._rule2update()

    @classmethod
    def rule2values(cls, rule):
        Rule = Pool().get('calendar.rrule')
        return Rule.rule2values(rule.calendar_rrule)

    @classmethod
    def rule2rule(cls, rule):
        Rule = Pool().get('calendar.rrule')
        return Rule.rule2rule(rule.calendar_rrule)


class TodoExDate(TodoRDate):
    'Exception Date'
    __name__ = 'calendar.todo.exdate'
    _table = 'calendar_todo_exdate'  # Needed to override TodoRDate._table


class TodoExRule(TodoRRule):
    'Exception Rule'
    __name__ = 'calendar.todo.exrule'
    _table = 'calendar_todo_exrule'  # Needed to override TodoRRule._table


class TodoAttendee(ModelSQL, ModelView):
    'Attendee'
    __name__ = 'calendar.todo.attendee'
    _inherits = {'calendar.attendee': 'calendar_attendee'}
    calendar_attendee = fields.Many2One('calendar.attendee',
        'Calendar Attendee', required=True, ondelete='CASCADE', select=True)
    todo = fields.Many2One('calendar.todo', 'Todo', ondelete='CASCADE',
            required=True, select=True)

    @classmethod
    def create(cls, values):
        Todo = Pool().get('calendar.todo')

        if values.get('todo'):
            # Update write_date of todo
            Todo.write([Todo(values['todo'])], {})
        attendee = super(TodoAttendee, cls).create(values)
        todo = attendee.todo
        if (todo.calendar.owner
                and (todo.organizer == todo.calendar.owner.email
                    or (todo.parent
                        and todo.parent.organizer == \
                            todo.parent.calendar.owner.email))):
            if todo.organizer == todo.calendar.owner.email:
                attendee_emails = [x.email for x in todo.attendees
                        if x.email != todo.organizer]
            else:
                attendee_emails = [x.email for x in todo.parent.attendees
                        if x.email != todo.parent.organizer]
            if attendee_emails:
                with Transaction().set_user(0):
                    todos = Todo.search([
                        ('uuid', '=', todo.uuid),
                        ('calendar.owner.email', 'in', attendee_emails),
                        ('id', '!=', todo.id),
                        ('recurrence', '=', todo.recurrence),
                        ])
                    for todo in todos:
                        cls.copy([attendee], default={
                            'todo': todo.id,
                            })
        return attendee

    @classmethod
    def write(cls, attendees, values):
        Todo = Pool().get('calendar.todo')

        todos = [x.todo.id for x in attendees]
        if values.get('todo'):
            todos.append(Todo(values['todo']))
        if todos:
            # Update write_date of todo
            Todo.write(todos, {})

        if 'email' in values:
            values = values.copy()
            del values['email']

        super(TodoAttendee, cls).write(attendees, values)
        for attendee in attendees:
            todo = attendee.todo
            if todo.calendar.owner \
                    and (todo.organizer == todo.calendar.owner.email \
                    or (todo.parent \
                    and todo.parent.organizer == todo.calendar.owner.email)):
                if todo.organizer == todo.calendar.owner.email:
                    attendee_emails = [x.email for x in todo.attendees
                            if x.email != todo.organizer]
                else:
                    attendee_emails = [x.email for x in todo.parent.attendees
                            if x.email != todo.parent.organizer]
                if attendee_emails:
                    with Transaction().set_user(0):
                        attendees2 = cls.search([
                            ('todo.uuid', '=', todo.uuid),
                            ('todo.calendar.owner.email', 'in',
                                    attendee_emails),
                            ('id', '!=', attendee.id),
                            ('todo.recurrence', '=', todo.recurrence),
                            ('email', '=', attendee.email),
                            ])
                        cls.write(attendees2, attendee._attendee2update())

    @classmethod
    def delete(cls, todo_attendees):
        pool = Pool()
        Todo = pool.get('calendar.todo')
        Attendee = pool.get('calendar.attendee')

        calendar_attendees = [a.calendar_attendee for a in todo_attendees]
        todos = [x.todo for x in todo_attendees]
        if todos:
            # Update write_date of todo
            Todo.write(todos, {})

        for attendee in todo_attendees:
            todo = attendee.todo
            if todo.calendar.owner \
                    and (todo.organizer == todo.calendar.owner.email \
                    or (todo.parent \
                    and todo.parent.organizer == todo.calendar.owner.email)):
                if todo.organizer == todo.calendar.owner.email:
                    attendee_emails = [x.email for x in todo.attendees
                            if x.email != todo.organizer]
                else:
                    attendee_emails = [x.email for x in todo.attendees
                            if x.email != todo.parent.organizer]
                if attendee_emails:
                    with Transaction().set_user(0):
                        attendees = cls.search([
                            ('todo.uuid', '=', todo.uuid),
                            ('todo.calendar.owner.email', 'in',
                                attendee_emails),
                            ('id', '!=', attendee.id),
                            ('todo.recurrence', '=', todo.recurrence),
                            ('email', '=', attendee.email),
                            ])
                        cls.delete(attendees)
            elif todo.calendar.organizer \
                    and ((todo.organizer \
                    or (todo.parent and todo.parent.organizer)) \
                    and attendee.email == todo.calendar.owner.email):
                if todo.organizer:
                    organizer = todo.organizer
                else:
                    organizer = todo.parent.organizer
                with Transaction().set_user(0):
                    attendees = cls.search([
                        ('todo.uuid', '=', todo.uuid),
                        ('todo.calendar.owner.email', '=', organizer),
                        ('id', '!=', attendee.id),
                        ('todo.recurrence', '=', todo.recurrence),
                        ('email', '=', attendee.email),
                        ])
                    if attendees:
                        cls.write(attendees, {
                            'status': 'declined',
                            })
        super(TodoAttendee, cls).delete(todo_attendees)
        if calendar_attendees:
            Attendee.delete(calendar_attendees)

    @classmethod
    def copy(cls, todo_attendees, default=None):
        Attendee = Pool().get('calendar.attendee')

        if default is None:
            default = {}
        default = default.copy()
        new_attendees = []
        for attendee in todo_attendees:
            default['calendar_attendee'], = Attendee.copy(
                [attendee.calendar_attendee])
            new_attendee, = super(TodoAttendee, cls).copy([attendee],
                default=default)
            new_attendees.append(new_attendee)
        return new_attendees

    def _attendee2update(self):
        return self.calendar_attendee._attendee2update()

    @classmethod
    def attendee2values(cls, attendee):
        Attendee = Pool().get('calendar.attendee')
        return Attendee.attendee2values(attendee.calendar_attendee)

    @classmethod
    def attendee2attendee(cls, attendee):
        Attendee = Pool().get('calendar.attendee')
        return Attendee.attendee2attendee(attendee.calendar_attendee)


class TodoAlarm(ModelSQL):
    'Alarm'
    __name__ = 'calendar.todo.alarm'
    _inherits = {'calendar.alarm': 'calendar_alarm'}
    calendar_alarm = fields.Many2One('calendar.alarm', 'Calendar Alarm',
            required=True, ondelete='CASCADE', select=True)
    todo = fields.Many2One('calendar.todo', 'Todo', ondelete='CASCADE',
            required=True, select=True)

    @classmethod
    def create(cls, values):
        Todo = Pool().get('calendar.todo')
        if values.get('todo'):
            # Update write_date of todo
            Todo.write([Todo(values['todo'])], {})
        return super(TodoAlarm, cls).create(values)

    @classmethod
    def write(cls, alarms, values):
        Todo = Pool().get('calendar.todo')
        todos = [x.todo for x in alarms]
        if values.get('todo'):
            todos.append(Todo(values['todo']))
        if todos:
            # Update write_date of todo
            Todo.write(todos, {})
        super(TodoAlarm, cls).write(alarms, values)

    @classmethod
    def delete(cls, todo_alarms):
        pool = Pool()
        Todo = pool.get('calendar.todo')
        Alarm = pool.get('calendar.alarm')
        alarms = [a.calendar_alarm for a in todo_alarms]
        todos = [x.todo for x in todo_alarms]
        if todos:
            # Update write_date of todo
            Todo.write(todos, {})
        super(TodoAlarm, cls).delete(todo_alarms)
        if alarms:
            Alarm.delete(alarms)

    @classmethod
    def valarm2values(cls, alarm):
        Alarm = Pool().get('calendar.alarm')
        return Alarm.valarm2values(alarm.calendar_alarm)

    def alarm2valarm(self, alarm):
        Alarm = Pool().get('calendar.alarm')
        return Alarm.alarm2valarm(alarm.calendar_alarm)
