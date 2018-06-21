import json

from django import forms
from bfrs.models import (Bushfire, AreaBurnt, Damage, Injury,BushfireSnapshot,DamageSnapshot,InjurySnapshot,AreaBurntSnapshot,
        Region, District, Profile,
        current_finyear,Tenure,Cause,
        reporting_years,Agency,BushfireProperty
    )
from datetime import datetime, timedelta
from django.conf import settings
from django.forms import ValidationError
from django.forms.models import inlineformset_factory, formset_factory, BaseInlineFormSet
from django.contrib import messages
from django.contrib.auth.models import User, Group
from django.contrib.gis.geos import Point, GEOSGeometry, Polygon, MultiPolygon, GEOSException

from crispy_forms.helper import FormHelper
from crispy_forms.layout import Layout, Fieldset, ButtonHolder, Submit, Div, HTML
from crispy_forms.bootstrap import TabHolder, Tab
from django.utils.safestring import mark_safe
from django.forms.widgets import Widget

from bfrs.utils import (can_maintain_data,)

from . import baseforms
from . import basewidgets
from .basefields import CompoundFieldFactory,OtherOptionFieldFactory,SwitchFieldFactory,CompoundField
from . import baselayouts
from . import basefields
from .utils import update_damage_fs, update_injury_fs

YESNO_CHOICES = (
    (True, 'Yes'),
    (False, 'No')
)

REPORTING_YEAR_CHOICES = ( reporting_years() )
print("{}".format(REPORTING_YEAR_CHOICES))

class HorizontalRadioRenderer(forms.RadioSelect.renderer):
    def render(self):
        return mark_safe(u'&nbsp;&nbsp;&nbsp;&nbsp;\n'.join([u'%s&nbsp;&nbsp;&nbsp;&nbsp;\n' % w for w in self]))


class VerticalRadioRenderer(forms.RadioSelect.renderer):
    def render(self):
        return mark_safe(u'<br />'.join([u'%s<br />' % w for w in self]))


class DisplayOnlyField(Widget):

    def __init__(self,attrs=None):
        self.attrs = attrs or {}
        self.required = False

    def render(self, name, value="", attrs=None):
        try:
            val = value
        except AttributeError:
            val = ""
        return val


class UserForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super(UserForm, self).__init__(*args, **kwargs)
        self.fields['is_active'].label = ("Approved User (i.e. enable login for this user?)")
        instance = getattr(self, 'instance', None)

    class Meta:
        model = User
        fields = ('is_active', 'groups', 'user_permissions',)


class GroupForm(forms.ModelForm):
    class Meta:
        model = Group
        exclude = ()



class BaseFormHelper(FormHelper):
    """
    Base helper class for rendering forms via crispy_forms.
    To remove the default "Save" button from the helper, instantiate it with
    inputs=[]
    E.g. helper = BaseFormHelper(inputs=[])
    """
    def __init__(self, *args, **kwargs):
        super(BaseFormHelper, self).__init__(*args, **kwargs)
        self.form_class = 'horizontal col-lg-2'
        self.help_text_inline = True
        self.form_method = 'POST'
        save_btn = Submit('submit', 'Save')
        save_btn.field_classes = 'btn btn-primary'
        cancel_btn = Submit('cancel', 'Cancel')
        self.add_input(save_btn)
        self.add_input(cancel_btn)


class HelperModelForm(forms.ModelForm):
    """
    Stock ModelForm with a property named ``helper`` (used by crispy_forms to
    render in templates).
    """
    @property
    def helper(self):
        helper = BaseFormHelper()
        return helper


class ProfileForm(HelperModelForm):
    def clean(self):
        """District must be child of Region.
        """
        cleaned_data = super(ProfileForm, self).clean()
        district = cleaned_data.get('district', None)
        if district and district.region != cleaned_data.get('region'):
            self._errors['district'] = self.error_class(
                ['Please choose a valid District for this Region (or leave it blank).'])
        # District may not be chosen if archive_date is set.
        if district and district.archive_date:
            self._errors['district'] = self.error_class(
                ['Please choose a current District for this Region (or leave it blank).'])
        return cleaned_data

    class Meta:
        model = Profile
        exclude = ('user',)


class BushfireFilterForm(forms.ModelForm):
    """
    django-filter module does not allow filter chaining
    Form are used to populate user interface, django-filter are used to filter query set.

    So passing a both form and filter to the context in the BushfireView, and still allowing the BushfireFilter to filter using the
    region and district passed from this form (i.e. region and filter are also declared in the BushfireFilter class)
    """

    YEAR_CHOICES = []
    RPT_YEAR_CHOICES = []
    STATUS_CHOICES = []
    try:
        YEAR_CHOICES = [[i['year'], i['year']] for i in Bushfire.objects.all().values('year').distinct()]
        RPT_YEAR_CHOICES = [[i['reporting_year'], i['reporting_year']] for i in Bushfire.objects.all().values('reporting_year').distinct()]
        STATUS_CHOICES = [(u'-1', '---------')] + list(Bushfire.REPORT_STATUS_CHOICES)
    except:
        pass

    year = forms.ChoiceField(choices=YEAR_CHOICES,required=False)
    reporting_year = forms.ChoiceField(choices=RPT_YEAR_CHOICES, required=False)
    include_archived = forms.BooleanField(required=False)
    exclude_missing_final_fire_boundary = forms.BooleanField(required=False)
    report_status = forms.ChoiceField(choices=STATUS_CHOICES, label='Report Status',required=False)
    def __init__(self, *args, **kwargs):
        super(BushfireFilterForm, self).__init__(*args, **kwargs)

        self.fields['region'].required = False
        self.fields['district'].required = False

        try:
            # allows dynamic update of the filter set, on page refresh
            self.fields["year"].choices = [[None, '---------']] + [[i['year'], str(i['year']) + '/' + str(i['year']+1)] for i in Bushfire.objects.all().values('year').distinct().order_by('year')]
            self.fields["reporting_year"].choices = [[None, '---------']] + [[i['reporting_year'], str(i['reporting_year']) + '/' + str(i['reporting_year']+1)] for i in Bushfire.objects.all().values('reporting_year').distinct().order_by('reporting_year')]
            # allows dynamic update of the filter set, on page refresh
            if not can_maintain_data(self.request.user):
                # pop the 'Reviewed' option
                self.fields['report_status'].choices = [(u'-1', '---------'), (1, 'Initial Fire Report'), (2, 'Notifications Submitted'), (3, 'Report Authorised'), (5, 'Invalidated'), (6, 'Outstanding Fires')]
        except:
            pass

    class Meta:
        fields = ('region', 'district')
        model = Bushfire


class BushfireUpdateForm(forms.ModelForm):
    dispatch_aerial = forms.ChoiceField(choices=YESNO_CHOICES, widget=forms.RadioSelect(renderer=HorizontalRadioRenderer), required=False)
    prob_fire_level = forms.ChoiceField(choices=Bushfire.FIRE_LEVEL_CHOICES, widget=forms.RadioSelect(renderer=HorizontalRadioRenderer), required=False)
    max_fire_level = forms.ChoiceField(choices=Bushfire.FIRE_LEVEL_CHOICES, widget=forms.RadioSelect(renderer=HorizontalRadioRenderer), required=False)
    investigation_req = forms.ChoiceField(choices=YESNO_CHOICES, widget=forms.RadioSelect(renderer=HorizontalRadioRenderer), required=False)
    cause_state = forms.ChoiceField(choices=Bushfire.CAUSE_STATE_CHOICES, widget=forms.RadioSelect(renderer=HorizontalRadioRenderer), required=False)
    origin_point_str = forms.CharField(required=False, widget=DisplayOnlyField())#, widget=forms.TextInput(attrs={'readonly':'readonly'}))
    media_alert_req = forms.ChoiceField(choices=YESNO_CHOICES, widget=forms.RadioSelect(renderer=HorizontalRadioRenderer), required=False)
    park_trail_impacted = forms.ChoiceField(choices=YESNO_CHOICES, widget=forms.RadioSelect(renderer=HorizontalRadioRenderer), required=False)
    dispatch_pw = forms.ChoiceField(choices=Bushfire.DISPATCH_PW_CHOICES, widget=forms.RadioSelect(renderer=HorizontalRadioRenderer), required=False)
    other_tenure = forms.ChoiceField(choices=Bushfire.IGNITION_POINT_CHOICES, widget=forms.RadioSelect(renderer=HorizontalRadioRenderer), required=False)
    arson_squad_notified = forms.ChoiceField(choices=YESNO_CHOICES, widget=forms.RadioSelect(renderer=HorizontalRadioRenderer), required=False)
    reporting_year = forms.ChoiceField(choices=REPORTING_YEAR_CHOICES, required=False, initial=REPORTING_YEAR_CHOICES[0][0])

    def __init__(self, *args, **kwargs):
        super (BushfireUpdateForm,self ).__init__(*args,**kwargs)
        # order alphabetically, but with username='other', as first item in list
        active_users = User.objects.filter(groups__name='Users').filter(is_active=True).exclude(username__icontains='admin').extra(select={'other': "CASE WHEN username='other' THEN 0 ELSE 1 END"}).order_by('other', 'username')
        self.fields['field_officer'].queryset = active_users
        self.fields['duty_officer'].queryset = active_users.exclude(username='other')
        self.fields['reporting_year'].initial = current_finyear()

        # For use when debugging outside SSS - need to create an origin_point manually
        #from django.contrib.gis.geos import Point, GEOSGeometry
        #self.fields['origin_point'].initial = GEOSGeometry(Point(122.45, -33.15))
        #self.fields['region'].initial = 1
        #self.fields['district'].initial = 1

    class Meta:
        model = Bushfire
        fields = ('sss_data', 'sss_id',
                  'region', 'district', 'dfes_incident_no',
                  'name', 'year', 'prob_fire_level', 'max_fire_level', 'duty_officer',
                  'field_officer', 'other_field_officer', 'other_field_officer_agency', 'other_field_officer_phone',
                  'media_alert_req', 'park_trail_impacted', 'fire_position', 'fire_position_override',
                  'fire_detected_date', 'dispatch_pw_date', 'dispatch_aerial_date',
                  'other_info',
                  'cause', 'cause_state', 'other_cause', 'prescribed_burn_id', 'tenure', 'other_tenure',
                  'dispatch_pw', 'dispatch_aerial',
                  'investigation_req',
                  'initial_area', 'initial_area_unknown', 'area', 'area_limit', 'other_area',
                  'origin_point_str', 'origin_point', 'origin_point_mga', 'fire_boundary',
                  'fire_not_found', 'fire_monitored_only', 'invalid_details',
                  'fire_contained_date', 'fire_controlled_date', 'fire_safe_date',
                  'first_attack', 'initial_control', 'final_control',
                  'other_first_attack', 'other_initial_control', 'other_final_control',
                  'arson_squad_notified', 'offence_no', 'job_code', 'reporting_year',
                  'damage_unknown','injury_unknown',
                 )

    def clean(self):
        cleaned_data = super(BushfireUpdateForm, self).clean()

        # Resetting forms fields declared above to None (from '') if None if not set in form
        if not self.cleaned_data['dispatch_pw']: self.cleaned_data['dispatch_pw'] = None
        if not self.cleaned_data['dispatch_aerial']: self.cleaned_data['dispatch_aerial'] = None
        if not self.cleaned_data['prob_fire_level']: self.cleaned_data['prob_fire_level'] = None
        if not self.cleaned_data['max_fire_level']: self.cleaned_data['max_fire_level'] = None
        if not self.cleaned_data['investigation_req']: self.cleaned_data['investigation_req'] = None
        if not self.cleaned_data['cause_state']: self.cleaned_data['cause_state'] = None
        if not self.cleaned_data['media_alert_req']: self.cleaned_data['media_alert_req'] = None
        if not self.cleaned_data['park_trail_impacted']: self.cleaned_data['park_trail_impacted'] = None
        if not self.cleaned_data['other_tenure']: self.cleaned_data['other_tenure'] = None

        if self.cleaned_data.has_key('job_code') and self.cleaned_data['job_code']:
            job_code = self.cleaned_data['job_code']
            if not job_code.isalpha() or len(job_code)!=3 or not job_code.isupper():
                self.add_error('job_code', 'Must be alpha characters, length 3, and uppercase, eg. UOV')

        if self.cleaned_data.has_key('fire_detected_date') and self.cleaned_data['fire_detected_date']:
            if self.cleaned_data.has_key('dispatch_pw_date') and self.cleaned_data['dispatch_pw_date'] and self.cleaned_data['dispatch_pw_date'] < self.cleaned_data['fire_detected_date']:
                self.add_error('dispatch_pw_date', 'Datetime must not be before Fire Detected Datetime.')
            if self.cleaned_data.has_key('dispatch_aerial_date') and self.cleaned_data['dispatch_aerial_date'] and self.cleaned_data['dispatch_aerial_date'] < self.cleaned_data['fire_detected_date']:
                self.add_error('dispatch_aerial_date', 'Datetime must not be before Fire Detected Datetime.')

        # FINAL Form
        if self.cleaned_data['fire_not_found']:
            self.cleaned_data['max_fire_level'] = None
            self.cleaned_data['arson_squad_notified'] = None
            self.cleaned_data['fire_contained_date'] = None
            self.cleaned_data['fire_controlled_date'] = None
            self.cleaned_data['fire_safe_date'] = None
            self.cleaned_data['first_attack'] = None
            self.cleaned_data['final_control'] = None
            self.cleaned_data['other_first_attack'] = None
            self.cleaned_data['other_initial_control'] = None
            self.cleaned_data['other_final_control'] = None
            self.cleaned_data['area'] = None
            self.cleaned_data['area_limit'] = False
            self.cleaned_data['arson_squad_notified'] = None
            self.cleaned_data['offence_no'] = None
            self.cleaned_data['reporting_year'] = None #current_finyear()
            self.cleaned_data['region_id'] = self.initial['region']
            self.cleaned_data['district_id'] = self.initial['district']
            return cleaned_data
        if self.cleaned_data['fire_monitored_only']:
            self.cleaned_data['first_attack'] = None
            self.cleaned_data['other_first_attack'] = None
        else:
            self.cleaned_data['invalid_details'] = None

        if self.cleaned_data['arson_squad_notified'] == '':
            self.cleaned_data['arson_squad_notified'] = None
        else:
            self.cleaned_data['arson_squad_notified'] = eval(self.cleaned_data['arson_squad_notified'])

        if self.cleaned_data.has_key('year') and self.cleaned_data.has_key('reporting_year') and int(self.cleaned_data['reporting_year']) < int(self.cleaned_data['year']):
            self.add_error('reporting_year', 'Cannot be before report financial year, {}/{}.'.format(self.cleaned_data['year'], int(self.cleaned_data['year'])+1))

        if self.cleaned_data.has_key('fire_detected_date') and self.cleaned_data['fire_detected_date']:
            if self.cleaned_data.has_key('fire_contained_date') and self.cleaned_data['fire_contained_date'] and self.cleaned_data['fire_contained_date'] < self.cleaned_data['fire_detected_date']:
                self.add_error('fire_contained_date', 'Datetime must not be before Fire Detected Datetime - {}.'.format(self.cleaned_data['fire_detected_date']))

        if self.cleaned_data.has_key('fire_contained_date') and self.cleaned_data['fire_contained_date']:
            if self.cleaned_data.has_key('fire_controlled_date') and self.cleaned_data['fire_controlled_date'] and self.cleaned_data['fire_controlled_date'] < self.cleaned_data['fire_contained_date']:
                self.add_error('fire_controlled_date', 'Datetime must not be before Fire Contained Datetime.')

        if self.cleaned_data.has_key('fire_controlled_date') and self.cleaned_data['fire_controlled_date']:
            if self.cleaned_data.has_key('fire_safe_date') and self.cleaned_data['fire_safe_date'] and self.cleaned_data['fire_safe_date'] < self.cleaned_data['fire_controlled_date']:
                self.add_error('fire_safe_date', 'Datetime must not be before Fire Controlled Datetime.')

        if self.cleaned_data.has_key('dispatch_pw_date') and self.cleaned_data['dispatch_pw_date'] and int(self.cleaned_data['dispatch_pw']) == Bushfire.DISPATCH_PW_NO:
            self.cleaned_data['dispatch_pw_date'] = None
        if self.cleaned_data.has_key('dispatch_aerial_date') and self.cleaned_data['dispatch_aerial_date'] and eval(self.cleaned_data['dispatch_aerial']) == False:
            self.cleaned_data['dispatch_aerial_date'] = None

        if self.cleaned_data.has_key('dispatch_pw') and self.cleaned_data['dispatch_pw']:
            self.cleaned_data['dispatch_pw'] = int(self.cleaned_data['dispatch_pw'])

        if self.cleaned_data.has_key('other_tenure') and self.cleaned_data['other_tenure']:
            self.cleaned_data['other_tenure'] = int(self.cleaned_data['other_tenure'])

        if self.cleaned_data.has_key('field_officer') and self.cleaned_data['field_officer'] and self.cleaned_data['field_officer'].username != 'other':
            self.cleaned_data['other_field_officer'] = None
            self.cleaned_data['other_field_officer_agency'] = None
            self.cleaned_data['other_field_officer_phone'] = None

        return cleaned_data

class FireCauseField(CompoundField):
    related_field_names = ("cause_state","other_cause","prescribed_burn_id")
    def _view_layout(self,f):
        cause = f.value()
        cause_state = f.related_fields[0].value()
        if cause and cause == Cause.OTHER:
            if cause_state == Bushfire.CAUSE_STATE_KNOWN:
                return ("Known<br>{}<br>{}",("other_cause",))
            elif cause_state == Bushfire.CAUSE_STATE_POSSIBLE:
                return ("Possible<br>{}<br>{}",("other_cause",))
            else:
                return ("{}<br>{}",("other_cause",))
        elif cause and cause == Cause.ESCAPE_DPAW_BURNING:
            if cause_state == Bushfire.CAUSE_STATE_KNOWN:
                return ("Known<br>{}<br>Burn ID: {}",("prescribed_burn_id",))
            elif cause_state == Bushfire.CAUSE_STATE_POSSIBLE:
                return ("Possible<br>{}<br>Burn ID: {}",("prescribed_burn_id",))
            else:
                return ("{}<br>Burn ID: {}",("prescribed_burn_id",))
        elif cause:
            if cause_state == Bushfire.CAUSE_STATE_KNOWN:
                return ("Known<br>{}",None)
            elif cause_state == Bushfire.CAUSE_STATE_POSSIBLE:
                return ("Possible<br>{}",None)
            else:
                return ("{}",None)
        else:
            if cause_state == Bushfire.CAUSE_STATE_KNOWN:
                return ("Known",None)
            elif cause_state == Bushfire.CAUSE_STATE_POSSIBLE:
                return ("Possible",None)
            else:
                return ("",None)

    def _edit_layout(self,f):
        cause = f.value()
        if cause == Cause.OTHER.id:
            basefields.hide_field(f.related_fields[2].field)
        elif cause == Cause.ESCAPE_DPAW_BURNING.id:
            basefields.hide_field(f.related_fields[1].field)
        else:
            basefields.hide_field(f.related_fields[1].field)
            basefields.hide_field(f.related_fields[2].field)
        f.field.widget.attrs = f.field.widget.attrs or {}
        f.field.widget.attrs["onchange"]="""
        if (this.value === '{0}') {{
            $("#{1}").show();
            $("#{1}").prop("disabled",false);
        }} else {{
            $("#{1}").hide();
            $("#{1}").prop("disabled",true);
        }}
        if(this.value === '{2}') {{
            $("#{3}").show()
            $("#{3}").prop("disabled",false);
        }} else {{
            $("#{3}").hide()
            $("#{3}").prop("disabled",true);
        }}
        """.format(Cause.OTHER.id,f.related_fields[1].auto_id,Cause.ESCAPE_DPAW_BURNING.id,f.related_fields[2].auto_id)
        return ("{1}<br>{0}<br>{2}{3}",f.field.related_field_names)

class FinalAreaField(CompoundField):
    related_field_names = ("final_fire_boundary","area_limit")
    def _view_layout(self,f):
        return ("{0}",None)

    def _edit_layout(self,f):
        final_boundary = f.related_fields[0].value()
        if final_boundary:
            f.field.widget.attrs["disabled"] = True
            return ("{0}",None)
        else:
            area_limit = f.related_fields[1].value()
            f.field.widget.attrs = f.field.widget.attrs or {}
            if not area_limit:
                f.field.widget.attrs["disabled"] = True
                f.field.widget.attrs["style"] = "display:none"

            f.related_fields[1].field.widget.attrs = f.related_fields[1].field.widget.attrs or {}
            f.related_fields[1].field.widget.attrs["onclick"]="""
            if (this.checked) {{
                $("#{0}").show();
                $("#{0}").prop("disabled",false);
            }} else {{
                $("#{0}").hide();
                $("#{0}").prop("disabled",true);
            }}
            """.format(f.auto_id)
            return ("{{1}} Area < {}ha<span style='margin: 20px;'></span>{{0}}".format(settings.AREA_THRESHOLD),("area_limit",))

class FirePositionField(CompoundField):
    related_field_names = ("fire_position_override",)
    def _view_layout(self,f):
        return ("{0}<br>SSS override - {1}",self.related_field_names)

    def _edit_layout(self,f):
        override = f.related_fields[0].value()
        f.field.widget.attrs = f.field.widget.attrs or {}
        if not override:
            f.field.widget.attrs["disabled"] = True

        f.field.widget.attrs = f.field.widget.attrs or {}

        f.related_fields[0].field.widget.attrs = f.related_fields[0].field.widget.attrs or {}
        f.related_fields[0].field.widget.attrs["onclick"]="""
            if (this.checked) {{
                $("#{0}").prop("disabled",false);
            }} else {{
                $("#{0}").prop("disabled",true);
            }}
            """.format(f.auto_id)
        return ("{0}<br>{1} SSS override",self.related_field_names)

class BaseBushfireViewForm(baseforms.ModelForm):
    submit_actions = None
    injury_formset = None
    damage_formset = None
    damages = None
    injuries = None 
    tenures_burnt = None

    def __init__(self, *args, **kwargs):
        if "request" in kwargs:
            self.request = kwargs.pop("request")
        else:
            self.request = None
        if "files" in kwargs and not kwargs["files"]:
            kwargs.pop("files")
        super (BaseBushfireViewForm,self ).__init__(*args,**kwargs)

    class Meta:
        model = Bushfire
        exclude = ('fb_validation_req','init_authorised_date','authorised_date','reviewed_date','report_status',
                    'archive','authorised_by','init_authorised_by','reviewed_by','valid_bushfire','fireboundary_uploaded_by',
                    'fireboundary_uploaded_date','capturemethod','other_capturemethod',"sss_data","sss_id")
        labels = {
            "initial_area_unknown":"Area of fire at arrival(ha)",
        }
        field_classes = {
            "__all__":forms.fields.CharField,
            "dispatch_pw":SwitchFieldFactory(Bushfire,"dispatch_pw",("dispatch_pw_date",),field_class=basefields.ChoiceFieldFactory(Bushfire.DISPATCH_PW_CHOICES,choice_class=forms.TypedChoiceField),true_value=1),
            "dispatch_aerial":SwitchFieldFactory(Bushfire,"dispatch_aerial",("dispatch_aerial_date",),field_class=basefields.ChoiceFieldFactory(YESNO_CHOICES)),
            "arson_squad_notified":SwitchFieldFactory(Bushfire,"arson_squad_notified",("offence_no",),policy=baselayouts.ALWAYS,on_layout="{0}<br>Police offence no: {1}",field_class=basefields.ChoiceFieldFactory(YESNO_CHOICES)),
            "initial_area_unknown":SwitchFieldFactory(Bushfire,"initial_area_unknown",("initial_area",),policy=baselayouts.ALWAYS,on_layout="Unknown",off_layout="{1}",reverse=True,edit_layout="{0} Unknown<br>{1}"),
            "initial_control":OtherOptionFieldFactory(Bushfire,"initial_control",("other_initial_control",),other_option=Agency.OTHER),
            "first_attack":OtherOptionFieldFactory(Bushfire,"first_attack",("other_first_attack",),other_option=Agency.OTHER),
            "final_control":OtherOptionFieldFactory(Bushfire,"final_control",("other_final_control",),other_option=Agency.OTHER),
            "tenure":OtherOptionFieldFactory(Bushfire,"tenure",("other_tenure",),other_option=Tenure.OTHER,policy=basefields.DATA_MAP,other_layout={1:"{0}<br>Private Property",2:"{0}<br>Other Crown"}),
            "origin_point":SwitchFieldFactory(Bushfire,"origin_point",("origin_point_mga",),true_value="",reverse=True,on_layout=u"{}",off_layout=u"{}<br>{}"),
            "field_officer":OtherOptionFieldFactory(Bushfire,"field_officer",("other_field_officer","other_field_officer_agency","other_field_officer_phone"),other_option=User.OTHER,policy=basefields.ALWAYS,other_layout=u"{}<br> Name: {}<br> Agency: {}<br> Phone: {}"),
            "cause":CompoundFieldFactory(FireCauseField,Bushfire,"cause"),
            "area":CompoundFieldFactory(FinalAreaField,Bushfire,"area"),
            "fire_position":CompoundFieldFactory(FirePositionField,Bushfire,"fire_position"),
            "investigation_req":basefields.ChoiceFieldFactory(YESNO_CHOICES),
            "media_alert_req":basefields.ChoiceFieldFactory(YESNO_CHOICES),
            "park_trail_impacted":basefields.ChoiceFieldFactory(YESNO_CHOICES),
            "prob_fire_level":basefields.ChoiceFieldFactory(Bushfire.FIRE_LEVEL_CHOICES,choice_class=forms.TypedChoiceField),
            "other_tenure":basefields.ChoiceFieldFactory(Bushfire.IGNITION_POINT_CHOICES,choice_class=forms.TypedChoiceField),
            "reporting_year":basefields.ChoiceFieldFactory(REPORTING_YEAR_CHOICES,choice_class=forms.TypedChoiceField),
        
        }
        widgets = {
            "__all__": basewidgets.TextDisplay(),
            "year":basewidgets.FinancialYearDisplay(),
            "reporting_year":basewidgets.FinancialYearDisplay(),
            "fire_detected_date":basewidgets.DatetimeDisplay(date_format="%Y-%m-%d %H:%M"),
            "init_authorised_date":basewidgets.DatetimeDisplay(date_format="%Y-%m-%d %H:%M"),
            "fire_contained_date":basewidgets.DatetimeDisplay(date_format="%Y-%m-%d %H:%M"),
            "fire_controlled_date":basewidgets.DatetimeDisplay(date_format="%Y-%m-%d %H:%M"),
            "fire_safe_date":basewidgets.DatetimeDisplay(date_format="%Y-%m-%d %H:%M"),
            "dispatch_pw_date":basewidgets.DatetimeDisplay(date_format="%Y-%m-%d %H:%M"),
            "dispatch_aerial_date":basewidgets.DatetimeDisplay(date_format="%Y-%m-%d %H:%M"),
            "fire_position_override":basewidgets.BooleanDisplay(),
            "investigation_req":basewidgets.BooleanDisplay(),
            "fire_not_found":basewidgets.BooleanDisplay(),
            "final_fire_boundary":basewidgets.BooleanDisplay(),
            "damage_unknown":basewidgets.BooleanDisplay(html_true="No damage to report",html_false=""),
            "injury_unknown":basewidgets.BooleanDisplay(html_true="No injuries/fatalities to report",html_false=""),
            "initial_area_unknown":basewidgets.BooleanDisplay(html_true="Unknown",html_false="Known"),
            "park_trail_impacted":basewidgets.TemplateDisplay(basewidgets.BooleanDisplay(),"{}<br> <span>PVS will be notified by email</span>"),
            "media_alert_req":basewidgets.TemplateDisplay(basewidgets.BooleanDisplay(),"{}<br> <span>call PICA on 9219 9999</span>"),
            "origin_point":basewidgets.DmsCoordinateDisplay(),
            "fire_monitored_only":basewidgets.BooleanDisplay(),
            "arson_squad_notified":basewidgets.BooleanDisplay(),
            "dispatch_pw":basewidgets.BooleanDisplay(),
            "dispatch_aerial":basewidgets.BooleanDisplay(),
        }


class BushfireViewForm(BaseBushfireViewForm):
    def __init__(self,*args,**kwargs):
        super(BushfireViewForm,self).__init__(*args,**kwargs)
        self.damages          = Damage.objects.filter(bushfire = self.instance)
        self.injuries         = Injury.objects.filter(bushfire = self.instance)
        self.tenures_burnt    = AreaBurnt.objects.filter(bushfire = self.instance)

    class Meta:
        model = Bushfire

class BushfireSnapshotViewForm(BaseBushfireViewForm):
    def __init__(self,*args,**kwargs):
        super(BushfireSnapshotViewForm,self).__init__(*args,**kwargs)
        self.damages          = DamageSnapshot.objects.filter(snapshot = self.instance)
        self.injuries         = InjurySnapshot.objects.filter(snapshot = self.instance)
        self.tenures_burnt    = AreaBurntSnapshot.objects.filter(snapshot = self.instance)

    class Meta:
        model = BushfireSnapshot

class BaseBushfireEditForm(BushfireViewForm):
    def __init__(self, *args, **kwargs):
        super (BaseBushfireEditForm,self ).__init__(*args,**kwargs)

        # order alphabetically, but with username='other', as first item in list
        if any([self.is_editable(field) for field in ('field_officer','duty_officer')]):
            active_users = User.objects.filter(groups__name='Users').filter(is_active=True).exclude(username__icontains='admin').extra(select={'other': "CASE WHEN username='other' THEN 0 ELSE 1 END"}).order_by('other', 'username')
            self.fields['field_officer'].queryset = active_users
            self.fields['duty_officer'].queryset = active_users.exclude(username='other')

        self.fields['reporting_year'].initial = current_finyear()
        if self.is_editable('tenure'):
            self.fields['tenure'].widget.attrs = self.fields['tenure'].widget.attrs or {}
            if self.instance:
                self.fields['tenure'].widget.attrs["disabled"] = True
            else:
                self.fields['tenure'].widget.attrs["readonly"] = True

        self.can_maintain_data = can_maintain_data(self.request.user) if self.request else False
        if self.instance and self.instance.pk:
            if self.instance.dfes_incident_no and not self.can_maintain_data and self.is_editable("dfes_incident_no"):
               self.fields["dfes_incident_no"].widget.attrs["disabled"] = True

    def is_valid(self):
        is_valid = super(BaseBushfireEditForm,self).is_valid()
        if  not (self.cleaned_data["fire_not_found"] if self.is_editable('fire_not_found') else self.instance.fire_not_found):
            if self.injury_formset:
                is_valid = self.injury_formset.is_valid(self.cleaned_data['injury_unknown']) and is_valid
            if self.damage_formset:
                is_valid = self.damage_formset.is_valid(self.cleaned_data['damage_unknown']) and is_valid

        return is_valid


    def clean(self):
        cleaned_data = super(BaseBushfireEditForm,self).clean()

        for name in ('prob_fire_level','max_fire_level','investigation_req','cause_state','media_alert_req','park_trail_impacted'):
            if self.is_editable(name) and not cleaned_data[name]:
                cleaned_data[name] = None

        if self.is_editable('dispatch_pw'):
            if self.intvalue(cleaned_data,'dispatch_pw',Bushfire.DISPATCH_PW_NO) == Bushfire.DISPATCH_PW_NO:
                cleaned_data["dispatch_pw_date"] = None

        if self.is_editable('dispatch_aerial'):
            if not self.boolvalue(cleaned_data,'dispatch_aerial'):
                cleaned_data["dispatch_aerial_date"] = None


        if self.is_editable('initial_area_unknown'):
            if self.boolvalue(cleaned_data,'initial_area_unknown'):
                cleaned_data['initial_area'] = None

        if self.is_editable('dfes_incident_no'):
            if not self.can_maintain_data and self.instance.dfes_incident_no:
                cleaned_data['dfes_incident_no'] = self.instance.dfes_incident_no

        if self.is_editable('fire_position'):
            if not self.boolvalue(cleaned_data,'fire_position_override'):
                cleaned_data["fire_position"] = self.instance.fire_position if self.instance else None

        if self.is_editable('job_code'):
            if cleaned_data.has_key('job_code') and cleaned_data['job_code']:
                job_code = cleaned_data['job_code']
                if not job_code.isalpha() or len(job_code)!=3 or not job_code.isupper():
                    self.add_error('job_code', 'Must be alpha characters, length 3, and uppercase, eg. UOV')

        if self.is_editable('tenure'):
            if self.instance and self.instance.pk:
                cleaned_data['tenure'] = self.instance.tenure
            if 'tenure' in cleaned_data:
                if cleaned_data['tenure'] !=Tenure.OTHER:
                    cleaned_data["other_tenure"] = None
                else:
                    self.intvalue(cleaned_data,"other_tenure")
            else:
                cleaned_data['tenure'] = None
                cleaned_data["other_tenure"] = None

        for item in ('fire_detected_date','dispatch_pw_date','dispatch_aerial_date','fire_contained_date','fire_controlled_date','fire_safe_date'):
            if self.is_editable(item) and (item not in cleaned_data  or not cleaned_data[item]):
                cleaned_data[item] = None

        if self.cleaned_data.has_key('year') and self.cleaned_data.has_key('reporting_year') and int(self.cleaned_data['reporting_year']) < int(self.cleaned_data['year']):
            self.add_error('reporting_year', 'Cannot be before report financial year, {}/{}.'.format(self.cleaned_data['year'], int(self.cleaned_data['year'])+1))

        if self.is_editable('field_officer'):
            if 'field_officer' in cleaned_data:
                if cleaned_data['field_officer'] !=User.OTHER:
                    cleaned_data['other_field_officer'] = None
                    cleaned_data['other_field_officer_agency'] = None
                    cleaned_data['other_field_officer_phone'] = None
            else:
                cleaned_data['field_officer'] = None
                cleaned_data['other_field_officer'] = None
                cleaned_data['other_field_officer_agency'] = None
                cleaned_data['other_field_officer_phone'] = None
        
        if self.is_editable('fire_not_found') and self.boolvalue(cleaned_data,'fire_not_found',False):
            cleaned_data['max_fire_level'] = None
            cleaned_data['arson_squad_notified'] = None
            cleaned_data['fire_contained_date'] = None
            cleaned_data['fire_controlled_date'] = None
            cleaned_data['fire_safe_date'] = None
            cleaned_data['first_attack'] = None
            cleaned_data['other_first_attack'] = None
            cleaned_data['final_control'] = None
            cleaned_data['other_final_control'] = None
            cleaned_data['initial_control'] = None
            cleaned_data['other_initial_control'] = None
            cleaned_data['area'] = None
            cleaned_data['area_limit'] = False
            cleaned_data['arson_squad_notified'] = None
            cleaned_data['offence_no'] = None
            cleaned_data['reporting_year'] = None #current_finyear()
            if self.is_editable('region'):
                cleaned_data['region'] = self.initial['region']
            if self.is_editable('district'):
                cleaned_data['district'] = self.initial['district']
        else:
            if self.is_editable('cause'):
                if 'cause' in cleaned_data:
                    if cleaned_data['cause'] != Cause.OTHER:
                      cleaned_data["other_cause"] = None
                    if cleaned_data['cause'] != Cause.ESCAPE_DPAW_BURNING:
                        cleaned_data["prescribed_burn_id"] = None
                else:
                    cleaned_data["cause"] = None

            if self.is_editable('area'):
                if self.instance and self.instance.final_fire_boundary:
                    cleaned_data['area'] = self.instance.area
                    cleaned_data['area_limit'] = False
                elif self.boolvalue(cleaned_data,'area_limit'):
                    self.floatvalue(cleaned_data,'area')
                else:
                    cleaned_data['area'] = None

            if self.is_editable('arson_squad_notified'):
                if not self.boolvalue(cleaned_data,'arson_squad_notified'):
                    cleaned_data["offence_no"] = None

            if self.is_editable('fire_monitored_only'):
                if cleaned_data['fire_monitored_only']:
                    cleaned_data['first_attack'] = None
                    cleaned_data['other_first_attack'] = None
                else:
                    cleaned_data['invalid_details'] = None

        if any([self.is_editable(item) for item in ('fire_detected_date','dispatch_pw_te','dispatch_aerial_date','fire_contained_date','fire_controlled_date','fire_safe_date')]) :
            fire_detected_date = cleaned_data['fire_detected_date'] if 'fire_detected_date' in cleaned_data  else (self.instance.fire_detected_date if self.instance else None)
            dispatch_pw_date = cleaned_data['dispatch_pw_date'] if 'dispatch_pw_date' in cleaned_data  else (self.instance.dispatch_pw_date if self.instance else None)
            dispatch_aerial_date = cleaned_data['dispatch_aerial_date'] if 'dispatch_aerial_date' in cleaned_data  else (self.instance.dispatch_aerial_date if self.instance else None)
            fire_contained_date = cleaned_data['fire_contained_date'] if 'fire_contained_date' in cleaned_data  else (self.instance.fire_contained_date if self.instance else None)
            fire_controlled_date = cleaned_data['fire_controlled_date'] if 'fire_controlled_date' in cleaned_data  else (self.instance.fire_controlled_date if self.instance else None)
            fire_safe_date = cleaned_data['fire_safe_date'] if 'fire_safe_date' in cleaned_data  else (self.instance.fire_safe_date if self.instance else None)

            if dispatch_pw_date and fire_detected_date and dispatch_pw_date < fire_detected_date:
                self.add_error('dispatch_pw_date', 'Datetime must not be before Fire Detected Datetime.')

            if dispatch_aerial_date and fire_detected_date and dispatch_aerial_date < fire_detected_date:
                self.add_error('dispatch_aerial_date', 'Datetime must not be before Fire Detected Datetime.')
                
            if fire_contained_date and fire_detected_date and fire_contained_date < fire_detected_date:
                self.add_error('fire_contained_date', 'Datetime must not be before Fire Detected Datetime - {}.'.format(fire_detected_date))

            if fire_controlled_date and fire_contained_date and fire_controlled_date < fire_contained_date:
                self.add_error('fire_controlled_date', 'Datetime must not be before Fire Contained Datetime.')

            if fire_safe_date and fire_controlled_date and fire_safe_date < fire_controlled_date:
                self.add_error('fire_safe_date', 'Datetime must not be before Fire Controlled Datetime.')

        return cleaned_data

    def _save_m2m(self):
        if self.is_editable("area"):
            if self.instance.area_limit:
                # if user selects there own final area, set the area to the tenure of ignition point (Tenure, Other Crown, (Other) Private Property)
                if self.instance.other_tenure == Bushfire.IGNITION_POINT_PRIVATE:
                    self.instance.tenures_burnt.exclude(tenure=Tenure.PRIVATE_PROPERTY).delete()
                    self.instance.tenures_burnt.update_or_create(tenure=Tenure.PRIVATE_PROPERTY, defaults={"area": self.instance.area})
                elif self.instance.other_tenure == Bushfire.IGNITION_POINT_CROWN:
                    self.instance.tenures_burnt.exclude(tenure=Tenure.OTHER_CROWN).delete()
                    self.instance.tenures_burnt.update_or_create(tenure=Tenure.OTHER_CROWN, defaults={"area": self.instance.area})
                elif not self.instance.other_tenure:
                    self.instance.tenures_burnt.exclude(tenure=self.instance.tenure).delete()
                    self.instance.tenures_burnt.update_or_create(tenure=self.instance.tenure, defaults={"area": self.instance.area})
            elif not self.instance.final_fire_boundary:
                #no final fire boundary, no area limit, delete the burning areas
                self.instance.tenures_burnt.all().delete()
            

        if self.is_editable('fire_not_found') and self.instance.fire_not_found:
            #fire not found
            Injury.objects.filter(bushfire=self.instance).delete()
            Damage.objects.filter(bushfire=self.instance).delete()
        else:
            if self.is_editable('injury_unknown'):
                injury_updated = update_injury_fs(self.instance, self.injury_formset)
            if self.is_editable('damage_unknown'):
                damage_updated = update_damage_fs(self.instance, self.damage_formset)


class MergedBushfireForm(BaseBushfireEditForm):
    submit_actions = [('save_merged','Save','btn-success')]
    def _post_clean(self):
        super(MergedBushfireForm,self)._post_clean()
        self.instance.modifier = self.request.user


    class Meta:
        model = Bushfire
        extra_update_fields = ('modified',)
        field_classes = {
            "__all__":forms.fields.CharField,
            "cause_state":basefields.ChoiceFieldFactory(Bushfire.CAUSE_STATE_CHOICES,choice_class=forms.TypedChoiceField),
        }
        widgets = {
            "arson_squad_notified":forms.RadioSelect(renderer=HorizontalRadioRenderer),
            "offence_no":forms.widgets.TextInput(attrs={"placeholder":"Police Offence No","title":"Police Offence No","style":"width:100%"}),
            "cause":None,
            "cause_state":forms.RadioSelect(renderer=HorizontalRadioRenderer),
            "other_cause":None,
            "prescribed_burn_id":forms.widgets.TextInput(attrs={"placeholder":"Burn ID","title":"Burn ID","style":"width:100%"}),
        }

class SubmittedBushfireForm(MergedBushfireForm):
    submit_actions = [('save_submitted','Save submitted report','btn-success'),('authorise','Save and Authorise','btn-warning')]
    def __init__(self,*args,**kwargs):
        super(SubmittedBushfireForm,self).__init__(*args,**kwargs)
        if self.request and self.request.POST and "sss_create" not in self.request.POST and self.is_editable("damage_unknown"):
            self.damage_formset          = DamageFormSet(self.request.POST, prefix='damage_fs')
        else:
            self.damage_formset = DamageFormSet(instance=self.instance, prefix='damage_fs')

        if self.request and self.request.POST and "sss_create" not in self.request.POST and self.is_editable("injury_unknown"):
            self.injury_formset          = InjuryFormSet(self.request.POST, prefix='injury_fs')
        else:
            self.injury_formset = InjuryFormSet(instance=self.instance, prefix='injury_fs')

    class Meta:
        model = Bushfire
        extra_update_fields = ('modified',)
        field_classes = {
            "__all__":forms.fields.CharField,
            "max_fire_level":basefields.ChoiceFieldFactory(Bushfire.FIRE_LEVEL_CHOICES,choice_class=forms.TypedChoiceField),
            "fire_not_found":SwitchFieldFactory(Bushfire,"fire_not_found",("invalid_details",),true_value=True),
        }
        widgets = {
            "dfes_incident_no":None,
            "field_officer":None,
            "other_field_officer":None,
            "other_field_officer_agency":None,
            "other_field_officer_phone":None,
            "fire_monitored_only":None,
            "job_code":None,
            "dispatch_aerial":forms.RadioSelect(renderer=HorizontalRadioRenderer),
            "dispatch_aerial_date":basewidgets.DatetimeInput(),
            "fire_contained_date":basewidgets.DatetimeInput(),
            "fire_controlled_date":basewidgets.DatetimeInput(),
            "fire_safe_date":basewidgets.DatetimeInput(),
            "first_attack":None,
            "other_first_attack":None,
            "fire_not_found":forms.CheckboxInput,
            "final_control":None,
            "other_final_control":None,
            "max_fire_level":forms.RadioSelect(renderer=HorizontalRadioRenderer),
            "area":forms.widgets.NumberInput(attrs={"step":0.01,"min":0,"max":settings.AREA_THRESHOLD}),
            "area_limit":None,
            "invalid_details":None,
            "damage_unknown":basewidgets.SwitchWidgetFactory(widget_class=basewidgets.TemplateWidgetFactory(widget_class=forms.CheckboxInput,template="{} No damage to report"),html_id="div_damage_unknown",reverse=True),
            "injury_unknown":basewidgets.SwitchWidgetFactory(widget_class=basewidgets.TemplateWidgetFactory(widget_class=forms.CheckboxInput,template="{} No injuries/fatalities to report"),html_id="div_injury_unknown",reverse=True),
            
        }

class SubmittedBushfireFSSGForm(SubmittedBushfireForm):
    class Meta:
        model = Bushfire
        widgets = {
            "region":None,
            "district":None,
            "reporting_year":None,
            "dispatch_pw":forms.RadioSelect(renderer=HorizontalRadioRenderer),
            "dispatch_pw_date":basewidgets.DatetimeInput(),
        }


class AuthorisedBushfireForm(SubmittedBushfireForm):
    submit_actions = [('save_final','Save final','btn-success')]

    class Meta:
        model = Bushfire

class AuthorisedBushfireFSSGForm(AuthorisedBushfireForm):
    class Meta:
        model = Bushfire
        widgets = {
            "region":None,
            "district":None,
            "reporting_year":None,
            "dispatch_pw":forms.RadioSelect(renderer=HorizontalRadioRenderer),
            "dispatch_pw_date":basewidgets.DatetimeInput(),
        }

class ReviewedBushfireForm(SubmittedBushfireForm):
    submit_actions = [('save_reviewed','Save final','btn-success')]

    class Meta:
        model = Bushfire

class ReviewedBushfireFSSGForm(ReviewedBushfireForm):
    class Meta:
        model = Bushfire
        widgets = {
            "region":None,
            "district":None,
            "reporting_year":None,
            "dispatch_pw":forms.RadioSelect(renderer=HorizontalRadioRenderer),
            "dispatch_pw_date":basewidgets.DatetimeInput(),
        }
class InitialBushfireForm(SubmittedBushfireForm):
    submit_actions = [('save_draft','Save draft','btn-success'),('submit','Save and Submit','btn-warning')]
    class Meta:
        model = Bushfire
        exclude = ('fb_validation_req','init_authorised_date','authorised_date','reviewed_date','report_status',
                    'archive','authorised_by','init_authorised_by','reviewed_by','valid_bushfire','fireboundary_uploaded_by',
                    'fireboundary_uploaded_date','capturemethod','other_capturemethod')
        extra_update_fields = ('modified',)
        field_classes = {
            "__all__":forms.fields.CharField,
        }
        widgets = {
            "__all__": basewidgets.TextDisplay(),
            "name":None,
            "fire_detected_date":basewidgets.DatetimeInput(),
            "duty_officer":None,
            "dispatch_pw":forms.RadioSelect(renderer=HorizontalRadioRenderer),
            "dispatch_pw_date":basewidgets.DatetimeInput(),
            "fire_position_override":None,
            "fire_position":None,
            "other_info":None,
            "investigation_req":forms.RadioSelect(renderer=HorizontalRadioRenderer),
            "prob_fire_level":forms.RadioSelect(renderer=HorizontalRadioRenderer),
            "initial_area_unknown":None,
            "initial_area":forms.widgets.NumberInput(attrs={"step":0.01,"min":0}),
            "initial_control":None,
            "other_initial_control":None,
            "tenure":None,
            "other_tenure":forms.RadioSelect(renderer=HorizontalRadioRenderer),
            "media_alert_req":basewidgets.SwitchWidgetFactory(forms.RadioSelect,true_value=True,html="<span>call PICA on 9219 9999</span>")(renderer=HorizontalRadioRenderer),
            "park_trail_impacted":basewidgets.SwitchWidgetFactory(forms.RadioSelect,true_value=True,html="<span>PVS will be notified by email</span>")(renderer=HorizontalRadioRenderer),
        }

class InitialBushfireFSSGForm(InitialBushfireForm):
    class Meta:
        model = Bushfire
        widgets = {
            "region":None,
            "district":None,
            "reporting_year":None,
        }

class BushfireCreateForm(InitialBushfireForm):
    submit_actions = [('create','Create','btn-success'),('submit','Create and Submit','btn-warning')]
    def __init__(self,*args,**kwargs):
        super(BushfireCreateForm,self).__init__(*args,**kwargs)
        self.plantations = None
        if "sss_data" not in self.initial:
            return
        sss = json.loads(self.initial['sss_data'])
        if sss.get('area') and sss['area'].get('total_area'):
            initial_area = round(float(sss['area']['total_area']), 2)
            self.initial['initial_area'] = initial_area if initial_area > 0 else 0.01

        # NOTE initial area (and area) includes 'Other Area', but recording separately to allow for updates - since this is not always provided, if area is not updated
        if sss.get('area') and sss['area'].get('other_area'):
            other_area = round(float(sss['area']['other_area']), 2)
            self.initial['other_area'] = other_area if other_area > 0 else 0.01

        if sss.get('origin_point') and isinstance(sss['origin_point'], list):
            self.initial['origin_point'] = Point(sss['origin_point'])

        if sss.has_key('origin_point_mga'):
            self.initial['origin_point_mga'] = sss['origin_point_mga']

        if sss.has_key('fire_position'):
            self.initial['fire_position'] = sss['fire_position']

        if sss.get('tenure_ignition_point') and sss['tenure_ignition_point'].get('category'):
            try:
                self.initial['tenure'] = Tenure.objects.get(name__istartswith=sss['tenure_ignition_point']['category'])
            except:
                self.initial['tenure'] = Tenure.objects.get(name='Other')
        else:
            self.initial['tenure'] = Tenure.objects.get(name='Other')

        if sss.get('region_id') and sss.get('district_id'):
            self.initial['region'] = Region.objects.get(id=sss['region_id'])
            self.initial['district'] = District.objects.get(id=sss['district_id'])

    def _post_clean(self):
        sss = json.loads(self.cleaned_data["sss_data"])

        if sss.get('tenure_ignition_point') and sss['tenure_ignition_point'].get('category'):
            try:
                self.cleaned_data['tenure'] = Tenure.objects.get(name__istartswith=sss['tenure_ignition_point']['category'])
            except:
                self.cleaned_data['tenure'] = Tenure.objects.get(name='Other')
        else:
            self.cleaned_data['tenure'] = Tenure.objects.get(name='Other')

        if sss.get('region_id') and sss.get('district_id'):
            self.instance.region = Region.objects.get(id=sss['region_id'])
            self.instance.district = District.objects.get(id=sss['district_id'])

        super(BushfireCreateForm,self)._post_clean()

        if self.instance.initial_area_unknown:
            self.instance.initial_area = None
            self.instance.other_area = None
        else:
            if sss.get('area') and sss['area'].get('total_area'):
                initial_area = round(float(sss['area']['total_area']), 2)
                self.instance.initial_area = initial_area if initial_area > 0 else 0.01

            if sss.get('area') and sss['area'].get('other_area'):
                other_area = round(float(sss['area']['other_area']), 2)
                self.instance.other_area = other_area if other_area > 0 else 0.01
            
        if sss.has_key('fire_position'):
            if not self.instance.fire_position_override:
                self.instance.fire_position = sss['fire_position']

        if sss.get('origin_point') and isinstance(sss['origin_point'], list):
            self.instance.origin_point = Point(sss['origin_point'])

        if sss.has_key('origin_point_mga'):
            self.instance.origin_point_mga = sss['origin_point_mga']

        if sss.get('sss_id') :
            self.instance.sss_id = sss['sss_id']

        if sss.get('fire_boundary') and isinstance(sss['fire_boundary'], list):
            self.instance.fire_boundary = MultiPolygon([Polygon(*p) for p in sss['fire_boundary']])
            sss.pop('fire_boundary')

        if sss.has_key('fb_validation_req'):
            self.instance.fb_validation_req = sss['fb_validation_req']

        if self.instance.fire_boundary:
            self.instance.fireboundary_uploaded_by = self.request.user
            self.instance.fireboundary_uploaded_date = timezone.now()

        self.plantations = None
        #get plantations data from sss_data, and remove it from sss_data because it is too big sometimes
        if sss.has_key("plantations"):
            self.plantations = sss.pop("plantations")
                
        self.instance.reporting_year = current_finyear()
        self.instance.creator = self.request.user
        self.instance.sss_data = json.dumps(sss)

    def _save_m2m(self):
        super(BushfireCreateForm,self)._save_m2m()
        if self.plantations:
            BushfireProperty.objects.create(bushfire=self.instance,name="plantations",value=json.dumps(self.plantations))

    class Meta:
        model = Bushfire
        field_classes = {
        }
        widgets = {
            "__all__": basewidgets.TextDisplay(),
            "sss_data":forms.widgets.HiddenInput(),
        }

class BaseInjuryFormSet(BaseInlineFormSet):
    def clean(self):
        """
        Adds validation to check:
            1. no duplicate (injury_type) combination
            2. all fields are filled
        """
        #import ipdb; ipdb.set_trace()
        #if any(self.errors):
        #    return

        duplicates = False
        injuries = []
        for form in self.forms:
            if form.cleaned_data:
                injury_type = form.cleaned_data['injury_type'] if form.cleaned_data.has_key('injury_type') else None
                number = form.cleaned_data['number'] if form.cleaned_data.has_key('number') else None
                remove = form.cleaned_data['DELETE'] if form.cleaned_data.has_key('DELETE') else False

                duplicates = False
                if not remove:
                    if not injury_type or not number:
                        #if either injury_type or number is null, the injury data will be removed if it exists; or ignored if it doesn't exist
                        form.cleaned_data['DELETE'] = True
                        continue

                    # Check that no two records have the same injury_type
                    if injury_type.name in injuries:
                        duplicates = True
                    else:
                        injuries.append((injury_type.name))

                    if duplicates:
                        form.add_error('injury_type', 'Duplicate: Injury type must be unique')

        return

    def is_valid(self, injury_unknown):
        if injury_unknown:
            # no need to validate formset
            #self.errors.pop()
            self.is_bound = False
            return True
        return super(BaseInjuryFormSet, self).is_valid()

class BaseDamageFormSet(BaseInlineFormSet):
    def clean(self):
        """
        Adds validation to check:
            1. no duplicate (damage_type) combination
            2. all fields are filled
        """
        duplicates = False
        damages = []

        for form in self.forms:
            if form.cleaned_data:
                damage_type = form.cleaned_data['damage_type'] if form.cleaned_data.has_key('damage_type') else None
                number = form.cleaned_data['number'] if form.cleaned_data.has_key('number') else None
                remove = form.cleaned_data['DELETE'] if form.cleaned_data.has_key('DELETE') else False

                duplicates = False
                if not remove:
                    if not damage_type or not number:
                        form.cleaned_data['DELETE'] = True
                        continue

                    # Check that no two records have the same damage_type
                    if damage_type.name in damages:
                        duplicates = True
                    else:
                        damages.append((damage_type.name))

                    if duplicates:
                        form.add_error('damage_type', 'Duplicate: Damage type must be unique')

        return

    def is_valid(self, damage_unknown):
        if damage_unknown:
            # no need to validate formset
            #self.errors.pop()
            self.is_bound = False
            return True
        return super(BaseDamageFormSet, self).is_valid()


#class BaseFireBehaviourFormSet(BaseInlineFormSet):
#    def clean(self):
#        """
#        Adds validation to check:
#            1. no duplicate (fuel_type) combination
#            2. all fields are filled
#        """
#        duplicates = False
#        fire_behaviour = []
#
#        for form in self.forms:
#            if form.cleaned_data:
#                fuel_type = form.cleaned_data['fuel_type'] if form.cleaned_data.has_key('fuel_type') else None
#                ros = form.cleaned_data['ros'] if form.cleaned_data.has_key('ros') else None
#                flame_height = form.cleaned_data['flame_height'] if form.cleaned_data.has_key('flame_height') else None
#                remove = form.cleaned_data['DELETE'] if form.cleaned_data.has_key('DELETE') else False
#
#                if not remove:
#                    if not fuel_type and not ros and not flame_height:
#                        form.cleaned_data['DELETE'] = True
#
#                    # Check that no two records have the same damage_type
#                    if fuel_type and ros and flame_height:
#                        if set([(fuel_type.name)]).issubset(fire_behaviour):
#                            duplicates = True
#                        fire_behaviour.append((fuel_type.name))
#
#                    if duplicates:
#                        form.add_error('fuel_type', 'Duplicate: Fuel type must be unique')
#
#        return


class AreaBurntForm(forms.ModelForm):
    class Meta:
        model = AreaBurnt
        fields = ('tenure', 'area',)

    def __init__(self, *args, **kwargs):
        super(AreaBurntForm, self).__init__(*args, **kwargs)
        if self.instance.id:
            self.fields['tenure'].widget.attrs['readonly'] = True
            self.fields['area'].widget.attrs['readonly'] = True


RECOMMENDATION_CHOICES = (
    (1, 'Noted'),
    (2, 'Noted/Endorsed'),
    (3, 'Noted/Endorsed with Amendment'),
    (4, 'Accept/Attending'),
)

class PDFReportForm(forms.Form):
    author = forms.CharField(max_length=100)
    position = forms.CharField(max_length=100)
    phone_no = forms.CharField(max_length=100)
    branch = forms.CharField(max_length=100, widget=forms.TextInput(attrs={'placeholder': 'eg. Fire Management Services Branch'}))
    division = forms.CharField(max_length=100, widget=forms.TextInput(attrs={'placeholder': 'eg. Regional and Fire Management Services Division'}))
    your_ref = forms.CharField(max_length=20, required=False)
    our_ref = forms.CharField(max_length=20, required=False)
    title = forms.CharField(max_length=50, widget=forms.TextInput(attrs={'placeholder': 'eg. BUSHFIRE SUPPRESSION'}))

    supplementary_text = forms.CharField(max_length=500, widget=forms.Textarea(), required=False)
    cost_implications = forms.CharField(max_length=250, widget=forms.Textarea(), required=False)
    urgency = forms.CharField(max_length=2500, widget=forms.Textarea(), required=False)
    contentious_issues = forms.CharField(max_length=250, widget=forms.Textarea(), required=False)
    sig_date = forms.CharField(max_length=20, required=True)
    recommendation = forms.ChoiceField(choices=RECOMMENDATION_CHOICES, widget=forms.RadioSelect(), initial=1,  required=True)


AreaBurntFormSet            = inlineformset_factory(Bushfire, AreaBurnt, extra=0, min_num=0, exclude=(), form=AreaBurntForm)
InjuryFormSet               = inlineformset_factory(Bushfire, Injury, formset=BaseInjuryFormSet, extra=1, max_num=7, min_num=0, validate_min=False, exclude=())
DamageFormSet               = inlineformset_factory(Bushfire, Damage, formset=BaseDamageFormSet, extra=1, max_num=7, min_num=0, validate_min=False, exclude=())
#FireBehaviourFormSet        = inlineformset_factory(Bushfire, FireBehaviour, formset=BaseFireBehaviourFormSet, extra=1, min_num=0, validate_min=False, exclude=())



