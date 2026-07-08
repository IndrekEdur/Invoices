from django.test import SimpleTestCase
from django.urls import reverse


class WorkspaceRouteTests(SimpleTestCase):
    routes = [
        ("workspace:home", "/workspace/"),
        ("workspace:dashboard", "/workspace/dashboard/"),
        ("workspace:inbox", "/workspace/inbox/"),
        ("workspace:projects", "/workspace/projects/"),
        ("workspace:documents", "/workspace/documents/"),
        ("workspace:reviews", "/workspace/reviews/"),
        ("workspace:search", "/workspace/search/"),
        ("workspace:assistant", "/workspace/assistant/"),
        ("workspace:settings", "/workspace/settings/"),
        ("workspace:design_system", "/workspace/design-system/"),
    ]

    def test_every_workspace_route_returns_http_200(self):
        for route_name, path in self.routes:
            with self.subTest(route_name=route_name):
                response = self.client.get(path)

                self.assertEqual(response.status_code, 200)

    def test_url_namespace_works(self):
        for route_name, path in self.routes:
            with self.subTest(route_name=route_name):
                self.assertEqual(reverse(route_name), path)

    def test_templates_render_base_layout(self):
        response = self.client.get(reverse("workspace:dashboard"))

        self.assertContains(response, "Operations Workspace Platform")
        self.assertContains(response, "Dashboard")
        self.assertContains(response, "workspace-content")

    def test_dashboard_cards_render(self):
        response = self.client.get(reverse("workspace:dashboard"))

        for title in ["Emails", "Projects", "Documents", "Reviews", "AI Suggestions", "Synchronization Status"]:
            with self.subTest(title=title):
                self.assertContains(response, title)

    def test_design_system_page_returns_http_200(self):
        response = self.client.get(reverse("workspace:design_system"))

        self.assertEqual(response.status_code, 200)

    def test_design_system_template_renders_key_component_labels(self):
        response = self.client.get(reverse("workspace:design_system"))

        for label in [
            "Primary Button",
            "Cards",
            "Badges and Status Badges",
            "Design System Table",
            "No items yet",
            "Form Field Wrapper",
        ]:
            with self.subTest(label=label):
                self.assertContains(response, label)

    def test_navigation_contains_design_system_link(self):
        response = self.client.get(reverse("workspace:dashboard"))

        self.assertContains(response, "Design System")
        self.assertContains(response, reverse("workspace:design_system"))
