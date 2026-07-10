from django import forms

from apps.accounting.models import AccountingIntegration
from apps.communications.models import EmailAccount


FIELD_CLASS = "mt-2 w-full rounded-xl border border-slate-300 px-3 py-2.5 text-sm"
FOCUS_FIELD_CLASS = (
    "mt-2 w-full rounded-xl border border-slate-300 px-3 py-2.5 text-sm "
    "outline-none transition focus:border-slate-500 focus:ring-4 focus:ring-slate-200"
)
CHECKBOX_CLASS = "h-4 w-4 rounded border-slate-300 text-slate-950"


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
