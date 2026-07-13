from django import forms
from datetime import date, timedelta

from apps.accounting.models import AccountingAccountClassification, AccountingIntegration
from apps.communications.models import EmailAccount
from apps.projects.models import Project
from apps.projects.services import ProjectStatusService


FIELD_CLASS = "mt-2 w-full rounded-xl border border-slate-300 px-3 py-2.5 text-sm"
FOCUS_FIELD_CLASS = (
    "mt-2 w-full rounded-xl border border-slate-300 px-3 py-2.5 text-sm "
    "outline-none transition focus:border-slate-500 focus:ring-4 focus:ring-slate-200"
)
CHECKBOX_CLASS = "h-4 w-4 rounded border-slate-300 text-slate-950"


def calendar_month_bounds(month_value):
    """Return inclusive first/last dates for a YYYY-MM calendar month."""
    try:
        year_text, month_text = str(month_value or "").strip().split("-", 1)
        year = int(year_text)
        month = int(month_text)
        month_start = date(year, month, 1)
    except (TypeError, ValueError) as exc:
        raise ValueError("Month must use YYYY-MM format.") from exc

    if month_start.month == 12:
        month_end = date(month_start.year, 12, 31)
    else:
        month_end = date(month_start.year, month_start.month + 1, 1) - timedelta(days=1)
    return month_start, month_end


class MonthlyGLSyncForm(forms.Form):
    integration = forms.ModelChoiceField(
        queryset=AccountingIntegration.objects.none(),
        widget=forms.Select(attrs={"class": FIELD_CLASS}),
    )
    month = forms.CharField(
        widget=forms.TextInput(attrs={"class": FIELD_CLASS, "type": "month"}),
    )

    def __init__(self, *args, organization=None, selected_month="", **kwargs):
        self.organization = organization
        super().__init__(*args, **kwargs)
        queryset = AccountingIntegration.objects.none()
        if organization:
            queryset = AccountingIntegration.objects.filter(
                organization=organization,
                provider=AccountingIntegration.Provider.MERIT,
                is_active=True,
            ).order_by("display_name", "id")
        self.fields["integration"].queryset = queryset
        self.fields["month"].initial = selected_month
        if queryset.count() == 1 and not self.data:
            self.fields["integration"].initial = queryset.first()

    def clean_month(self):
        month = (self.cleaned_data["month"] or "").strip()
        try:
            self.month_start, self.month_end = calendar_month_bounds(month)
        except ValueError as exc:
            raise forms.ValidationError(str(exc)) from exc
        return month

    def clean_integration(self):
        integration = self.cleaned_data["integration"]
        if not self.organization or integration.organization_id != self.organization.id:
            raise forms.ValidationError("Choose an integration for the current organization.")
        if integration.provider != AccountingIntegration.Provider.MERIT:
            raise forms.ValidationError("Monthly GL sync currently supports only Merit integrations.")
        if not integration.is_active:
            raise forms.ValidationError("Choose an active Merit integration.")
        return integration


class EmailAccountForm(forms.ModelForm):
    secret = forms.CharField(
        label="Secret / password",
        required=False,
        widget=forms.PasswordInput(
            attrs={
                "autocomplete": "new-password",
                "class": FOCUS_FIELD_CLASS,
            }
        ),
    )

    class Meta:
        model = EmailAccount
        fields = [
            "provider",
            "display_name",
            "email_address",
            "username",
            "host",
            "port",
            "use_ssl",
            "use_tls",
            "auth_type",
            "is_active",
        ]
        widgets = {
            "provider": forms.Select(attrs={"class": FIELD_CLASS}),
            "display_name": forms.TextInput(attrs={"class": FIELD_CLASS}),
            "email_address": forms.EmailInput(attrs={"class": FIELD_CLASS}),
            "username": forms.TextInput(attrs={"class": FIELD_CLASS}),
            "host": forms.TextInput(attrs={"class": FIELD_CLASS}),
            "port": forms.NumberInput(attrs={"class": FIELD_CLASS}),
            "auth_type": forms.TextInput(attrs={"class": FIELD_CLASS}),
            "use_ssl": forms.CheckboxInput(attrs={"class": CHECKBOX_CLASS}),
            "use_tls": forms.CheckboxInput(attrs={"class": CHECKBOX_CLASS}),
            "is_active": forms.CheckboxInput(attrs={"class": CHECKBOX_CLASS}),
        }

    def __init__(self, *args, **kwargs):
        self.organization = kwargs.pop("organization", None)
        super().__init__(*args, **kwargs)
        if not self.instance.pk:
            self.fields["secret"].required = True

    def save(self, commit=True):
        instance = super().save(commit=False)
        if self.organization and not instance.organization_id:
            instance.organization = self.organization

        secret = self.cleaned_data.get("secret", "")
        if secret:
            instance.encrypted_secret_placeholder = secret

        if commit:
            instance.save()
            self.save_m2m()
        return instance


class AccountingIntegrationForm(forms.ModelForm):
    secret = forms.CharField(
        label="API secret",
        required=False,
        widget=forms.PasswordInput(
            attrs={
                "autocomplete": "new-password",
                "class": FOCUS_FIELD_CLASS,
            }
        ),
    )
    project_dimension_id = forms.CharField(
        label="Merit project dimension id",
        required=False,
        widget=forms.TextInput(attrs={"class": FIELD_CLASS}),
        help_text="Stored in integration metadata for project dimension value creation.",
    )

    class Meta:
        model = AccountingIntegration
        fields = [
            "provider",
            "display_name",
            "api_base_url",
            "api_id",
            "is_active",
        ]
        widgets = {
            "provider": forms.Select(attrs={"class": FIELD_CLASS}),
            "display_name": forms.TextInput(attrs={"class": FIELD_CLASS}),
            "api_base_url": forms.URLInput(attrs={"class": FIELD_CLASS}),
            "api_id": forms.TextInput(attrs={"class": FIELD_CLASS}),
            "is_active": forms.CheckboxInput(attrs={"class": CHECKBOX_CLASS}),
        }

    def __init__(self, *args, **kwargs):
        self.organization = kwargs.pop("organization", None)
        super().__init__(*args, **kwargs)
        self.fields["project_dimension_id"].initial = (self.instance.metadata or {}).get("project_dimension_id", "")
        if not self.instance.pk:
            self.fields["secret"].required = True

    def save(self, commit=True):
        instance = super().save(commit=False)
        if self.organization and not instance.organization_id:
            instance.organization = self.organization

        secret = self.cleaned_data.get("secret", "")
        if secret:
            instance.encrypted_secret_placeholder = secret

        metadata = dict(instance.metadata or {})
        project_dimension_id = self.cleaned_data.get("project_dimension_id", "").strip()
        if project_dimension_id:
            metadata["project_dimension_id"] = project_dimension_id
        else:
            metadata.pop("project_dimension_id", None)
        instance.metadata = metadata

        if commit:
            instance.save()
            self.save_m2m()
        return instance


class AccountClassificationForm(forms.Form):
    category = forms.ChoiceField(
        choices=AccountingAccountClassification.Category.choices,
        widget=forms.Select(attrs={"class": FIELD_CLASS}),
    )
    reporting_sign = forms.ChoiceField(
        choices=[("1", "1 - keep source sign"), ("-1", "-1 - reverse source sign")],
        widget=forms.Select(attrs={"class": FIELD_CLASS}),
        help_text="Revenue accounts stored as credit/negative allocations may require -1 so report revenue appears positive.",
    )
    include_in_project_result = forms.BooleanField(
        required=False,
        initial=True,
        widget=forms.CheckboxInput(attrs={"class": CHECKBOX_CLASS}),
    )
    is_active = forms.BooleanField(
        required=False,
        initial=True,
        widget=forms.CheckboxInput(attrs={"class": CHECKBOX_CLASS}),
    )
    notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"class": FIELD_CLASS, "rows": 4}),
    )

    def __init__(self, *args, classification=None, **kwargs):
        super().__init__(*args, **kwargs)
        if classification:
            self.fields["category"].initial = classification.category
            self.fields["reporting_sign"].initial = str(classification.reporting_sign)
            self.fields["include_in_project_result"].initial = classification.include_in_project_result
            self.fields["is_active"].initial = classification.is_active
            self.fields["notes"].initial = classification.notes
        else:
            self.fields["category"].initial = AccountingAccountClassification.Category.UNCLASSIFIED
            self.fields["reporting_sign"].initial = "1"


class ProjectEditForm(forms.ModelForm):
    class Meta:
        model = Project
        fields = [
            "name",
            "description",
            "project_type",
            "start_date",
            "end_date",
        ]
        widgets = {
            "name": forms.TextInput(attrs={"class": FIELD_CLASS}),
            "description": forms.Textarea(attrs={"class": FIELD_CLASS, "rows": 4}),
            "project_type": forms.Select(attrs={"class": FIELD_CLASS}),
            "start_date": forms.DateInput(attrs={"class": FIELD_CLASS, "type": "date"}),
            "end_date": forms.DateInput(attrs={"class": FIELD_CLASS, "type": "date"}),
        }


class ProjectStatusChangeForm(forms.Form):
    new_status = forms.ChoiceField(widget=forms.Select(attrs={"class": FIELD_CLASS}))
    reason = forms.CharField(
        required=False,
        widget=forms.Textarea(
            attrs={
                "class": FIELD_CLASS,
                "rows": 2,
                "placeholder": "Optional reason for audit history",
            }
        ),
    )

    def __init__(self, *args, project=None, **kwargs):
        super().__init__(*args, **kwargs)
        choices = []
        if project:
            allowed_statuses = ProjectStatusService.ALLOWED_TRANSITIONS.get(project.status, set())
            choices = [(status, label) for status, label in Project.Status.choices if status in allowed_statuses]
        self.fields["new_status"].choices = choices
