from django import forms

from apps.communications.models import EmailAccount


class EmailAccountForm(forms.ModelForm):
    secret = forms.CharField(
        label="Secret / password",
        required=False,
        widget=forms.PasswordInput(
            attrs={
                "autocomplete": "new-password",
                "class": "mt-2 w-full rounded-xl border border-slate-300 px-3 py-2.5 text-sm outline-none transition focus:border-slate-500 focus:ring-4 focus:ring-slate-200",
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
            "provider": forms.Select(attrs={"class": "mt-2 w-full rounded-xl border border-slate-300 px-3 py-2.5 text-sm"}),
            "display_name": forms.TextInput(attrs={"class": "mt-2 w-full rounded-xl border border-slate-300 px-3 py-2.5 text-sm"}),
            "email_address": forms.EmailInput(attrs={"class": "mt-2 w-full rounded-xl border border-slate-300 px-3 py-2.5 text-sm"}),
            "username": forms.TextInput(attrs={"class": "mt-2 w-full rounded-xl border border-slate-300 px-3 py-2.5 text-sm"}),
            "host": forms.TextInput(attrs={"class": "mt-2 w-full rounded-xl border border-slate-300 px-3 py-2.5 text-sm"}),
            "port": forms.NumberInput(attrs={"class": "mt-2 w-full rounded-xl border border-slate-300 px-3 py-2.5 text-sm"}),
            "auth_type": forms.TextInput(attrs={"class": "mt-2 w-full rounded-xl border border-slate-300 px-3 py-2.5 text-sm"}),
            "use_ssl": forms.CheckboxInput(attrs={"class": "h-4 w-4 rounded border-slate-300 text-slate-950"}),
            "use_tls": forms.CheckboxInput(attrs={"class": "h-4 w-4 rounded border-slate-300 text-slate-950"}),
            "is_active": forms.CheckboxInput(attrs={"class": "h-4 w-4 rounded border-slate-300 text-slate-950"}),
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
