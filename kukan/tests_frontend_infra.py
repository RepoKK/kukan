"""Tests for the Stage 10 frontend infrastructure: the unified `base.html`,
the `{% icon %}` tag and the toast region.

`login.html` is the first (and, for this stage, only) page built on this
infrastructure — it was already Vue-free, which is why the plan picks it as
the smallest possible proof that the new base template works end to end.
"""
from django.contrib import messages
from django.contrib.messages.storage.base import Message
from django.template import Context, Template
from django.template.loader import render_to_string
from django.test import SimpleTestCase, TestCase
from django.urls import reverse


class IconTagTest(SimpleTestCase):
    def render(self, tag_args, context=None):
        template = Template('{% load icons %}{% icon ' + tag_args + ' %}')
        return template.render(Context(context or {}))

    def test_renders_the_mdi_class(self):
        html = self.render("'check'")
        self.assertIn('mdi mdi-check', html)
        self.assertIn('class="icon"', html)

    def test_size_is_appended_as_a_bulma_modifier(self):
        html = self.render("'medal' size='is-small'")
        self.assertIn('class="icon is-small"', html)

    def test_the_name_is_escaped(self):
        """Buefy's `<b-icon>` never took untrusted input either, but the tag
        should not be a new injection point if that ever changes."""
        html = self.render('name', {'name': '"><script>alert(1)</script>'})
        self.assertNotIn('<script>', html)


class ToastsPartialTest(SimpleTestCase):
    def render(self, message_list):
        return render_to_string('ui/toasts.html', {'messages': message_list})

    def test_no_messages_renders_nothing(self):
        html = self.render([])
        self.assertNotIn('toast-region', html)

    def test_a_success_message_gets_the_bulma_success_class(self):
        html = self.render([Message(messages.SUCCESS, 'Saved.')])
        self.assertIn('is-success', html)
        self.assertIn('Saved.', html)

    def test_an_error_message_maps_to_bulma_danger_not_error(self):
        """Bulma's notification component has no `.error` modifier; Django's
        default tag for this level is the string "error", which would render
        with no colour at all without the MESSAGE_TAGS override in settings."""
        html = self.render([Message(messages.ERROR, 'Broken.')])
        self.assertIn('is-danger', html)
        self.assertNotIn('notification error', html)

    def test_dismiss_is_alpine_driven_not_javascript_from_scratch(self):
        """A hand-written dismiss button would duplicate what Alpine already
        does; this pins that the partial actually uses it instead."""
        html = self.render([Message(messages.INFO, 'Hi.')])
        self.assertIn('x-data', html)
        self.assertIn('x-show', html)


class LoginPageUsesTheNewBaseTest(TestCase):
    """login.html has no Vue at all, which is why Stage 10 starts there: it
    proves base.html, the vendored libraries and the static paths work
    together before anything harder is ported onto them."""

    def test_vendored_libraries_are_linked(self):
        response = self.client.get(reverse('login'))
        self.assertContains(response, 'vendor/htmx/htmx.min.js')
        self.assertContains(response, 'vendor/alpinejs/alpine.min.js')
        self.assertContains(response, 'vendor/bulma/bulma.min.css')
        self.assertContains(response, 'vendor/mdi/css/materialdesignicons.min.css')

    def test_no_vue_or_buefy_remains(self):
        response = self.client.get(reverse('login'))
        content = response.content.decode()
        self.assertNotIn('vue_app', content)
        self.assertNotIn('buefy', content.lower())
        self.assertNotIn('node_modules', content)

    def test_the_form_still_renders_and_posts(self):
        """A regression net for the port, not a new test of Django auth: the
        old template's behaviour must survive the base-template swap."""
        from django.contrib.auth.models import User
        User.objects.create_user('alice', password='hunter2')

        get_response = self.client.get(reverse('login'))
        self.assertContains(get_response, 'name="username"')
        self.assertContains(get_response, 'name="password"')

        post_response = self.client.post(reverse('login'), {
            'username': 'alice', 'password': 'hunter2'})
        self.assertRedirects(post_response, '/')
