"""Tests for `ui/navbar.html` and `base_ext.html`: the HTMX/Alpine port of
`vue/vue_navbar.html`, the shared chrome every non-leaf page below it uses.

Rendered directly with `render_to_string(..., request=request)` rather than
through a real view, because no page is wired onto `base_ext.html` yet in
this stage — the navbar is built once, ahead of the pages that will use it,
matching the plan's Wave B ordering ("navbar ... must land first").
"""
from django.contrib.auth.models import User
from django.template import RequestContext, Template
from django.template.loader import render_to_string
from django.test import RequestFactory, TestCase
from django.urls import reverse


class NavbarPartialTest(TestCase):
    def setUp(self):
        self.request = RequestFactory().get('/')
        self.request.user = User.objects.create_user('alice', password='x')

    def render(self, has_search=True, **context):
        """`has_search` defaults to True here, in Python, rather than via a
        Django template filter default: `{{ value|default:True }}` treats
        any falsy value — including an explicit `False` — as "unset", so it
        cannot represent has_search=False at all. The template itself takes
        no default; every real include site passes it explicitly."""
        context['has_search'] = has_search
        return render_to_string('ui/navbar.html', context, request=self.request)

    def test_search_form_is_shown_by_default(self):
        html = self.render()
        self.assertIn('name="search"', html)

    def test_search_form_is_hidden_when_has_search_is_false(self):
        """index.html passes has_search=False: its whole body is already a
        search form, so the small navbar one would be a confusing duplicate.

        Caught a real bug while writing this: the template briefly read
        `{% if has_search|default:True %}`, and Django's `default` filter
        substitutes on *any* falsy value, not just an unset one — so an
        explicit has_search=False silently became True and the form never
        hid. The template now checks `has_search` with no filter at all."""
        html = self.render(has_search=False)
        self.assertNotIn('name="search"', html)

    def test_main_nav_links_are_present(self):
        html = self.render()
        self.assertIn(reverse('kukan:kanji_list'), html)
        self.assertIn(reverse('kukan:yoji_list'), html)
        self.assertIn(reverse('kukan:kotowaza_list'), html)

    def test_example_dropdown_preserves_the_filtered_query_strings(self):
        """These four URLs are an internal API (kukan/views.py Index.form_valid
        constructs matching ones server-side) — the exact query string is
        what must survive the port, not just the base path."""
        html = self.render()
        base = reverse('kukan:example_list')
        self.assertIn(f'{base}?意味=kaki', html)
        self.assertIn(f'{base}?意味=yomi', html)
        self.assertIn(f'{base}?意味=hyogai', html)
        self.assertIn(f'{base}?意味=kotowaza', html)

    def test_misc_dropdown_links_are_present(self):
        html = self.render()
        self.assertIn(reverse('kukan:test_result_list'), html)
        self.assertIn(reverse('kukan:stats'), html)
        self.assertIn(reverse('kukan:export'), html)
        self.assertIn(reverse('bustime:bustime_main'), html)
        self.assertIn(reverse('session_list'), html)

    def test_logout_is_a_post_form_not_a_link(self):
        """LogoutView has been POST-only since Django 5.0; a GET is a 405.
        The regression this guards is the exact one the old vue_navbar.html
        comment calls out, now carried into the port."""
        html = self.render()
        self.assertIn(f'action="{reverse("logout")}"', html)
        self.assertIn('method="post"', html)
        self.assertNotIn(f'href="{reverse("logout")}"', html)

    def test_the_logged_in_username_is_shown(self):
        html = self.render()
        self.assertIn('alice', html)

    def test_the_burger_and_dropdowns_are_alpine_driven(self):
        """No hand-rolled navbar-burger click listener like the old
        base.html's — this pins that Alpine owns it instead."""
        html = self.render()
        self.assertIn('x-data', html)
        self.assertIn('@click="open = !open"', html)


class BaseExtTest(TestCase):
    """`base_ext.html` is the app-shell every page except login.html and
    index.html is expected to extend from Wave B on."""

    def render_dummy_page(self):
        template = Template(
            "{% extends 'base_ext.html' %}"
            "{% block content %}<p id='marker'>hi</p>{% endblock %}")
        request = RequestFactory().get('/')
        request.user = User.objects.create_user('bob', password='x')
        return template.render(RequestContext(request))

    def test_content_block_is_rendered_inside_the_shell(self):
        html = self.render_dummy_page()
        self.assertIn("<p id='marker'>hi</p>", html)

    def test_the_fixed_navbar_compensation_class_is_applied(self):
        """Bulma requires `has-navbar-fixed-top` on <html> (or a fixed-top
        ancestor) so page content is not rendered underneath the navbar."""
        html = self.render_dummy_page()
        self.assertIn('class="has-navbar-fixed-top"', html)

    def test_the_navbar_is_included(self):
        html = self.render_dummy_page()
        self.assertIn('navbar-burger', html)
