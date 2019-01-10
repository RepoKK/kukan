from django.db.models.base import ModelBase


class OrderFromAttr:
    """
    Class decorator adding rich comparison methods based on one attribute of the class
    """
    def __init__(self, comp_attr):
        self.comp_attr = comp_attr
        self.comp_operators = ['eq', 'ne', 'lt', 'lt', 'gt', 'ge']

    def create_operator_function(self, opname):
        def operator_function(me, other):
            try:
                return getattr(getattr(me, self.comp_attr), opname)(getattr(other, self.comp_attr))
            except (AttributeError, TypeError):
                return NotImplemented

        operator_function.__name__ = opname
        operator_function.__doc__ = getattr(int, opname).__doc__
        return operator_function

    def __call__(self, cls):
        for opname in ['__{}__'.format(i) for i in self.comp_operators]:
            setattr(cls, opname, self.create_operator_function(opname))
        return cls


class QuickGetKey:
    """
    Class decorator for Django model adding quick access to objects based on a single primary key.

    Example: by adding the @QuickGetKey('reference') decorator to a Book Model, the following statements are equivalent:
        Book.objects.get(reference='ABC')       # Normal Django syntax
        Book.qget('ABC')
    """
    def __init__(self, key_field):
        self.key_field = key_field

    def __call__(self, decorated_class):
        def _qget(cls, key):
            return cls.objects.get(**{cls.key_field: key})

        decorated_class.key_field = self.key_field
        decorated_class.qget = classmethod(_qget)

        return decorated_class
