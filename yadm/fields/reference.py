"""
Work with references.

.. code-block:: python

    class RDoc(Document):
        i = fields.IntegerField()

    class Doc(Document):
        rdoc = fields.ReferenceField(RDoc)

    rdoc = RDoc()
    rdoc.i = 13
    db.insert(rdoc)

    doc = Doc()
    doc.rdoc = rdoc
    db.insert(doc)

    doc = db.get_queryset(Doc).find_one(doc.id)  # reload doc
    assert doc.rdoc.id == rdoc.id
    assert doc.rdoc.i == 13

Or asynchronous:

.. code-block:: python

    rdoc = await doc.rdoc
    assert rdoc.id == rdoc.id
    assert rdoc.i == 13
    assert doc.rdoc == rdoc.id
"""
import asyncio

from bson import ObjectId
from bson.errors import InvalidId

from yadm.common import EnclosedDocDescriptor
from yadm.markers import AttributeNotSet
from yadm.documents import Document
from yadm.fields.base import Field, pass_null
from yadm.testing import create_fake


class BrokenReference(Exception):
    """ Raise if referrenced document is not found.
    """


class NotBindingToDatabase(Exception):  # noqa
    """ Raise if set ObjectId insted referenced document
    to new document, who not binded to database.
    """


class ReferenceField(Field):
    """ Field for work with references.

    :param reference_document_class: class for refered documents
    """
    reference_document_class = EnclosedDocDescriptor('reference')

    def __init__(self, reference_document_class, **kwargs):
        super().__init__(**kwargs)
        self.reference_document_class = reference_document_class

    def get_default(self, document):
        if self.smart_null:
            return None
        else:
            return AttributeNotSet

    def get_fake(self, document, faker, depth):
        """ Try create referenced document.
        """
        res = create_fake(
            self.reference_document_class,
            __db__=document.__db__,
            __faker__=faker,
            __depth__=depth)

        if res is AttributeNotSet and self.smart_null:
            return None
        else:
            return res

    def copy(self):
        return self.__class__(self.reference_document_class,
                              smart_null=self.smart_null)

    @pass_null
    def prepare_value(self, document, value):
        if isinstance(value, Document):
            return value
        elif value is AttributeNotSet:
            return AttributeNotSet
        else:
            if isinstance(value, str):
                try:
                    value = ObjectId(value)
                except InvalidId:
                    pass

            return self.from_mongo(document, value)

    @pass_null
    def from_mongo(self, document, value):
        if document.__db__ is not None:
            rdc = self.reference_document_class

            if document.__qs__ is not None:
                cache = document.__qs__.cache
                key = (rdc, value)

                if cache is not None and key in cache:
                    return cache[key]

            else:
                cache = None
                key = None

            qs = document.__db__.get_queryset(rdc, cache=cache)
            result = qs.find_one(value, exc=BrokenReference)

            if asyncio.iscoroutine(result):
                result = Reference(value, document, self, result)

            if cache is not None:
                cache[key] = result

            return result

        else:
            raise NotBindingToDatabase((document, self, value))

    @pass_null
    def to_mongo(self, document, value):
        return value.id


class Reference(ObjectId):
    """ Reference object.

    This is awaitable:

        doc = await reference
    """
    document = None

    def __init__(self, _id, parent, field, find_one_coro):
        super().__init__(_id)
        self.parent = parent
        self.field = field
        self.find_one_coro = find_one_coro

    def __repr__(self):
        n = self.__class__.__name__
        collection = self.field.reference_document_class.__collection__

        if self.document is None:
            status = '-'
        else:
            status = '+'

        return "{}({}:{} {})".format(n, collection, str(self), status)

    def __await__(self):
        return (yield from self.get())

    @asyncio.coroutine
    def get(self, force=False):
        if self.document is None:
            self.document = yield from self.find_one_coro

        return self.document
