import hmac
import json
import urllib
import hashlib

from django.db.models import Max
from django.shortcuts import render
from django.http import Http404, HttpResponseRedirect, HttpResponse
from django.conf import settings
from django.core.mail import send_mail
from django.contrib.messages import success
from django.core.urlresolvers import reverse
from django.utils.translation import ugettext_lazy as _, activate, get_language
from django.views.decorators.vary import vary_on_headers
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator, PageNotAnInteger, EmptyPage
from django.views.decorators.cache import cache_page

from wagtail.wagtailcore.models import Page, Site
from wagtail.wagtailadmin.forms import SearchForm
from wagtail.wagtailadmin.views.pages import preview_on_edit

from .models import HomePage, StaticPage, GuidelinesPage
from category.models import Category
from .forms import ContactForm, DonateForm

from core.utils import get_translations_for_page
from collections import OrderedDict

def home_page(request, slug="home-page"):
    home_page = HomePage.objects.get(slug=slug)
    translations = get_translations_for_page(home_page)
    video = home_page.video
    talking_album = home_page.talking_album
    photo_album = home_page.photo_album
    home_context = {
        'talking_album': {
            'image': talking_album.slides.first().image,
            'count':talking_album.slides.count(),
            'photographers': get_unique_photographers(talking_album),
            'section_model': talking_album,
        },
        'photo_album': {
            'image': photo_album.slides.first().image,
            'count': photo_album.slides.count(),
            'photographers': get_unique_photographers(photo_album),
            'section_model': photo_album,
        },
        'video': {
            'image': video.featured_image,
            'photographers': video.authors.all(),
            'section_model': video,
        },
        "page": home_page,
        "categories": Category.objects.all(),
        "translations": translations,
        "current_page": 'home-page',
    }
    return render(request, "core/home_page.html", home_context)

def get_unique_photographers(talking_album):
    photographers = []
    for slide in talking_album.slides.all():
        photographers.extend(slide.image.photographers.all())
    return set(photographers)


def static_page(request, slug=None):
    try:
        page = Page.objects.get(slug=slug)
    except Page.DoesNotExist:
        raise Http404
    if page.specific_class == HomePage:
        return home_page(request, page.slug)
    active_tab = 'about-pari'
    if 'donate' in slug:
        active_tab = 'donate'
    translations = get_translations_for_page(page.specific)
    return render(request, "core/static_page.html", {
        "self": page.specific,
        "translations": translations,
        "tab": active_tab,
        "current_page": slug,
    })

def guidelines(request):
    guideline = GuidelinesPage.objects.first()
    page_content = construct_guidelines(guideline.content)
    active_tab = 'about-pari'
    return render(request, "core/guidelines.html", {
        "page": guideline,
        "page_content": page_content,
        "tab": active_tab,
    })

def contribute_to_faces(request,slug=None):
    active_tab = 'about-pari'
    link = 'https://script.google.com/macros/s/AKfycbzMQwyY8P1t7CT0_ylmPfSDz7WiSTVHWtL-Yf0UhtoYOIWQfMf5/exec'
    return render(request, "core/contribute-to-faces.html",
                  {"tab": active_tab,
                   "link": link,
                   "current_page": 'contribute_to_faces',
                   })

def pari_teachers_students(request):
    active_tab = 'about-pari'
    return render(request, "core/pari_teachers_students.html", {
        "tab": active_tab,
        "current_page": 'pari_teachers_students',
    })


def construct_guidelines(guideline_content):
    guideline_dict = OrderedDict()
    for content in guideline_content:
        if content.block_type == "heading_title":
            current_heading = content.value
            guideline_dict[current_heading] = {"sub_section": []}
        if content.block_type == "heading_content":
            guideline_dict[current_heading]["heading_content"] = content.value
        if content.block_type == "sub_section_with_heading":
            guideline_dict[current_heading]["has_sub_section_with_heading"] = True
            guideline_dict[current_heading]["sub_section"].append(content.value)
        if content.block_type == "sub_section_without_heading":
            guideline_dict[current_heading]["has_sub_section_with_heading"] = False
            guideline_dict[current_heading]["sub_section"].append({"content": content.value})
    return guideline_dict

def contribute(request, slug=None):
    page = StaticPage.objects.get(slug=slug)
    return render(request, "core/contribute.html", {
        "self": page,
        "tab": 'about-pari',
        "current_page": 'contribute',
    })


def contact_us(request):
    if request.method == "POST":
        form = ContactForm(request.POST)
        if form.is_valid():
            form.save()
            success(request, _("Your query has successfully been sent"))
            form = ContactForm()
    else:
        form = ContactForm()
    return render(request, "core/contact_us.html", {
        "contact_form": form,
        "tab": "about-pari",
        "current_page": 'contact_us',
    })


# TODO: Remove the below two functions when we migrate to wagtail 1.2

DEFAULT_PAGE_KEY = 'p'


def paginate(request, items, page_key=DEFAULT_PAGE_KEY, per_page=20):
    page = request.GET.get(page_key, 1)

    paginator = Paginator(items, per_page)
    try:
        page = paginator.page(page)
    except PageNotAnInteger:
        page = paginator.page(1)
    except EmptyPage:
        page = paginator.page(paginator.num_pages)

    return paginator, page


@vary_on_headers('X-Requested-With')
def search(request):
    pages = []
    q = None

    if 'q' in request.GET:
        form = SearchForm(request.GET)
        if form.is_valid():
            q = form.cleaned_data['q']

            pages = Page.objects.all().prefetch_related('content_type').search(q)
            paginator, pages = paginate(request, pages)
    else:
        form = SearchForm()

    if request.is_ajax():
        return render(request, "wagtailadmin/pages/search_results.html", {
            'pages': pages,
            'query_string': q,
            'pagination_query_params': ('q=%s' % q) if q else ''
        })
    else:
        return render(request, "wagtailadmin/pages/search.html", {
            'search_form': form,
            'pages': pages,
            'query_string': q,
            'pagination_query_params': ('q=%s' % q) if q else ''
        })


def donate_form(request):
    form = DonateForm()
    errors = None
    try:
        site = Site.objects.get(hostname=request.get_host())
    except Site.DoesNotExist:
        site = Site.objects.filter(is_default_site=True)[0]
    if request.method == "POST":
        form = DonateForm(request.POST)
        if form.is_valid():
            pg_url = settings.INSTAMOJO["DONATE_URL"]
            params = {
                "data_name": form.cleaned_data["name"],
                "data_email": form.cleaned_data["email"],
                "data_phone": form.cleaned_data["phone"],
                "data_Field_90444": form.cleaned_data["pan"],
            }
            pg_url += "?{0}".format(urllib.urlencode(params))
            return HttpResponseRedirect(pg_url)
    return render(request, 'core/donate_form.html', {
        "form": form,
        "errors": errors,
        "site": site,
        "current_page": 'donate_form',
    })


def donate_success(request):
    try:
        site = Site.objects.get(hostname=request.get_host())
    except Site.DoesNotExist:
        site = Site.objects.filter(is_default_site=True)[0]
    return render(request, 'core/donate_success.html', {
        "site": site,
        "current_page": 'donate_success',
    })


def lower_first_item(item):
    return item[0].lower()


@csrf_exempt
@require_POST
def donate_webhook(request):
    status = 400
    data = request.POST.copy()
    hook_mac = data.pop("mac", [None])[0]
    keys = sorted(data.items(), key=lower_first_item)
    vals = "|".join([ii[1] for ii in keys])
    calc_mac = hmac.new(
        settings.INSTAMOJO["SALT"],
        vals,
        hashlib.sha1).hexdigest()
    if hook_mac == calc_mac:
        if data["status"] == "Credit":
            status = 200
            subject = _("Donation received")
            message = u""
            for (kk, vv) in data.items():
                message += unicode(kk) + u" : " + unicode(vv) + u"\r\n"
            send_mail(
                subject, message,
                settings.DEFAULT_FROM_EMAIL,
                settings.DONATE_EMAIL_RECIPIENTS
            )
    return HttpResponse("", status=status)


@login_required
@require_POST
def page_preview(request, page_id):
    curr_lang = get_language()
    rendered_response = None
    if request.POST.get("language"):
        activate(request.POST["language"])
    try:
        response = preview_on_edit(request, page_id)
        if getattr(response, "rendered_content", None):
            rendered_response = response.rendered_content
            response.content = rendered_response
    finally:
        activate(curr_lang)
    return response


@cache_page(86400)
def sitemap_index(request):
    site = Site.objects.get(hostname=request.get_host())
    pages = Page.objects.filter(live=True).exclude(title="Translations")
    years = pages.datetimes("first_published_at", "year") \
        .order_by("-datetimefield")
    last_upd = []
    for year in years:
        last_upd.append(pages.filter(first_published_at__year=year.year) \
                        .aggregate(dt=Max("latest_revision_created_at")))
    return render(request, "sitemaps/sitemap.xml", {
        "site": site,
        "years": zip(years, last_upd)
    }, content_type="text/xml")


@cache_page(86400)
def sitemap_year(request, year=None):
    site = Site.objects.get(hostname=request.get_host())
    pages = Page.objects.filter(live=True).exclude(title="Translations")
    pages = pages.filter(first_published_at__year=year)
    return render(request, "sitemaps/sitemap-year.xml", {
        "site": site,
        "pages": pages
    }, content_type="text/xml")
