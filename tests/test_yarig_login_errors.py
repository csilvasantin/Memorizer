import unittest

from src.yarig import _extract_login_error_text, YarigClient


class YarigLoginErrorTests(unittest.TestCase):
    def test_extract_login_error_translates_invalid_email(self):
        html = """
        <form id="login">
          <p class="clue-error">The Email field must contain a valid email address.</p>
        </form>
        """
        self.assertEqual(
            _extract_login_error_text(html),
            "el email de Yarig.ai no es valido; usa una direccion completa",
        )

    def test_operation_error_uses_login_detail(self):
        client = YarigClient(email="usuario", password="secret")
        client._remember_error("login_failed", detail="el email de Yarig.ai no es valido; usa una direccion completa")
        self.assertEqual(
            client.operation_error("cargar el panel de Yarig.ai"),
            "⚠️ No se pudo cargar el panel de Yarig.ai: el email de Yarig.ai no es valido; usa una direccion completa.",
        )
