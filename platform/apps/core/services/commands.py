from dataclasses import dataclass


@dataclass(frozen=True)
class CreateOrganizationCommand:
    name: str
    legal_name: str = ""
    organization_type: str = "company"
    registration_number: str = ""
    vat_number: str = ""
    country: str = "EE"
    timezone: str = "Europe/Tallinn"
    currency: str = "EUR"
