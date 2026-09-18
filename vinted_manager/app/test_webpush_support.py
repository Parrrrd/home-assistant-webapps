import base64
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from cryptography.hazmat.primitives.asymmetric import ec

from webpush_support import encrypt_webpush_payload, load_or_create_vapid_private_key, vapid_public_key_b64


def b64d(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


class WebPushSupportTests(unittest.TestCase):
    def test_rfc8291_vector(self):
        ua_public = "BCVxsr7N_eNgVRqvHtD0zTZsEc6-VV-JvLexhqUzORcxaOzi6-AYWXvTBHm4bjyPjs7Vd8pZGH6SRpkNtoIAiw4"
        auth = "BTBZMqHH6r4Tts7J_aSIgg"
        sender_private = "yfWPiYE-n46HLnH0KqZOF1fJJU3MYrct3AELtAQ-oRw"
        salt = "DGv6ra1nlYgDCS1FRnbzlw"
        private_key = ec.derive_private_key(int.from_bytes(b64d(sender_private), "big"), ec.SECP256R1())
        body = encrypt_webpush_payload(
            {"keys": {"p256dh": ua_public, "auth": auth}},
            b"When I grow up, I want to be a watermelon",
            sender_private_key=private_key,
            salt=b64d(salt),
        )
        actual = base64.urlsafe_b64encode(body).decode("ascii").rstrip("=")
        expected = (
            "DGv6ra1nlYgDCS1FRnbzlwAAEABBBP4z9KsN6nGRTbVYI_c7VJSPQTBtkgcy27ml"
            "mlMoZIIgDll6e3vCYLocInmYWAmS6TlzAC8wEqKK6PBru3jl7A_yl95bQpu6cVPT"
            "pK4Mqgkf1CXztLVBSt2Ks3oZwbuwXPXLWyouBWLVWGNWQexSgSxsj_Qulcy4a-fN"
        )
        self.assertEqual(actual, expected)

    def test_vapid_key_persists(self):
        with TemporaryDirectory() as temp:
            path = Path(temp) / "vapid.pem"
            first = vapid_public_key_b64(path)
            second = vapid_public_key_b64(path)
            self.assertEqual(first, second)
            self.assertEqual(len(b64d(first)), 65)
            self.assertTrue(path.is_file())
            self.assertIsNotNone(load_or_create_vapid_private_key(path))


if __name__ == "__main__":
    unittest.main()
