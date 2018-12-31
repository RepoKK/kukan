from unittest import TestCase
from utilsdjango.decorators import OrderFromAttr


class OrderFromAttrDecorator(TestCase):

    @OrderFromAttr('value')
    class TestClass:
        def __init__(self, name, value):
            self.value = value
            self.name = name

        def __repr__(self):
            return self.name

    def assertListStrictlyIdentical(self, first, second):
        self.assertCountEqual(first, second)
        for a, b in zip(first, second):
            self.assertIs(a, b)

    def test_all(self):
        test_a = self.TestClass('A', 5)
        test_b = self.TestClass('B', 3)
        test_c = self.TestClass('C', 5)

        self.assertIs(test_a, test_a)
        self.assertIsNot(test_a, test_c)

        self.assertEqual(test_a, test_c)
        self.assertGreaterEqual(test_a, test_c)
        self.assertLessEqual(test_a, test_c)
        self.assertNotEqual(test_a, test_b)
        self.assertGreaterEqual(test_a, test_b)
        self.assertGreater(test_a, test_b)
        self.assertLessEqual(test_b, test_c)
        self.assertLess(test_b, test_c)

        self.assertListStrictlyIdentical([test_b, test_c, test_a], sorted([test_c, test_a, test_b]))
        with self.assertRaises(AssertionError):
            self.assertListStrictlyIdentical([test_b, test_a, test_c], sorted([test_c, test_a, test_b]))
        self.assertEqual([test_b, test_a, test_c], sorted([test_c, test_a, test_b]))

    def test_ComparisonAgainstOtherTypes(self):
        test_a = self.TestClass('A', 5)
        with self.assertRaises(AssertionError):
            self.assertEqual(test_a, 5)

