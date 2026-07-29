"""FilteredListView: the HTMX/Alpine replacement for AjaxList.

`AjaxList` serves an HTML shell, then a Vue table re-requests the same URL
with `?ajax=1` and renders whatever JSON comes back (kukan/views.py). This
serves one response instead: the full page on a normal request, or just the
`<table>` + pagination fragment when `request.htmx` says the request came
from one of the page's own `hx-get` links (a filter form submission, a
column-sort click, or a page-change link). That fragment is `ui/_table.html`,
shared by every view that switches over.

`FFilter.add_to_query()` and `TableData` are reused unchanged -- only the
rendering layer differs. Pagination itself is Django's own `ListView`
machinery (`paginate_by`), not the hand-rolled `Paginator` calls `AjaxList`
needed because it had to serialise a JSON envelope by hand.
"""
import time

from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import ListView


class FilteredListView(LoginRequiredMixin, ListView):
    paginate_by = 20
    table_data = None       # a kukan.views.TableData instance
    filters = []            # a list of FFilter instances
    default_sort = None
    list_title = ''
    # {field_name: template_name}. An escape hatch for a column that needs
    # more than TableData's format callable can give it -- e.g. yoji_list's
    # 日課 column, which renders a per-row Alpine widget that needs the whole
    # object (and the page's own csrf_token), not just one formatted value.
    # Included via {% include %}, so it shares the page's real render
    # context; a value built through TableData.format() would not.
    cell_overrides = {}

    def get_sortable_fields(self):
        """Field names the table actually displays -- the only ones worth
        ordering by. Ported from AjaxList.get_sortable_fields."""
        return {col['field'] for col in self.table_data.get_col_template()}

    def clean_sort_by(self, sort_by):
        """Constrain `sort_by` to the displayed columns. Ported from
        AjaxList.clean_sort_by: an unknown name or a relation traversal
        (`?sort_by=kanjis__kanjidetails__anki_English`) used to reach
        order_by() directly and either 500 or run an expensive hidden join."""
        if not sort_by:
            return self.default_sort
        if sort_by.removeprefix('-') in self.get_sortable_fields():
            return sort_by
        return self.default_sort

    @property
    def sort_by(self):
        return self.clean_sort_by(
            self.request.GET.get('sort_by', self.default_sort))

    def get_queryset(self):
        qry = self.model.objects.all()
        for flt in self.filters:
            qry = flt.filter(self.request, qry)
        return qry.order_by(self.sort_by)

    #: Replaced when the filter form applies: chips and rows together, so the
    #: bar's state comes back from the query string rather than being patched
    #: in place by Alpine.
    filter_partial_template_name = 'ui/_filter_results.html'
    #: Replaced by a sort header or a page link, which change neither the
    #: filters nor which chips are up.
    partial_template_name = 'ui/_table.html'

    def get_template_names(self):
        if not self.request.htmx:
            return [self.template_name]
        if self.request.htmx.target == 'filter-results':
            return [self.filter_partial_template_name]
        return [self.partial_template_name]

    #: Page links either side of the current one before the ellipsis, and at
    #: each end. Django's Paginator.get_elided_page_range defaults (3 and 2)
    #: give 9 links on a middle page; these give the tighter run the Buefy
    #: table used to show.
    pagination_on_each_side = 2
    pagination_on_ends = 1

    def get_context_data(self, **kwargs):
        started = time.perf_counter()
        context = super().get_context_data(**kwargs)
        columns = self.table_data.get_col_template()
        context['columns'] = columns
        # list() and .count both hit the database; everything measured by
        # `query_ms` below is inside them.
        object_list = list(context['object_list'])
        paginator, page = context['paginator'], context['page_obj']
        context['query_ms'] = int((time.perf_counter() - started) * 1000)

        # Whole page numbers plus Paginator.ELLIPSIS markers, rather than one
        # link per page: kanji_list is 310 pages, and the first version of
        # this template emitted all 310.
        #
        # list(), because get_elided_page_range returns a generator: the
        # template consumes it, and anything that looks afterwards -- another
        # {% include %}, or a test -- finds it empty.
        context['page_window'] = list(paginator.get_elided_page_range(
            page.number,
            on_each_side=self.pagination_on_each_side,
            on_ends=self.pagination_on_ends)) if paginator.num_pages > 1 else []
        context['page_ellipsis'] = paginator.ELLIPSIS

        context['rows'] = list(zip(
            self.table_data.get_table_data(object_list), object_list,
            strict=True))
        context['cell_overrides'] = self.cell_overrides
        context['sort_by'] = self.sort_by
        context['active_sort_field'] = self.sort_by.removeprefix('-')
        context['sort_descending'] = self.sort_by.startswith('-')
        # For each column, the sort_by value a click on its header should
        # request next: the reverse of the current direction if it is
        # already the active column, ascending otherwise.
        context['sort_links'] = {
            col['field']: f'-{col["field"]}'
            if col['field'] == context['active_sort_field']
            and not context['sort_descending'] else col['field']
            for col in columns
        }
        context['list_title'] = self.list_title
        context['filters'] = [
            (flt, self.request.GET.get(flt.label, '')) for flt in self.filters]
        # Which chips the filter bar shows without being asked. A filter
        # carrying a value in the query string is visible; the rest sit behind
        # the "add filter" dropdown. This is the `active_filters` the Vue bar
        # took as indices, by label instead -- the labels are the query-string
        # keys, so they survive a filter being reordered on the view.
        shown = {label for label
                 in self.request.GET.get('_show', '').split(',') if label}
        context['active_filter_labels'] = [
            flt.label for flt in self.filters
            if self.request.GET.get(flt.label) or flt.label in shown]
        context['all_filter_labels'] = [flt.label for flt in self.filters]
        return context
