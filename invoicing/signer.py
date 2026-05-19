import base64
from lxml import etree
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

class XMLSigner:

    @staticmethod
    def load_private_key(path, password=None):
        """
        تحميل المفتاح الخاص (Private Key)
        """
        with open(path, "rb") as key_file:
            return serialization.load_pem_private_key(
                key_file.read(),
                password=password.encode() if password else None
            )

    @staticmethod
    def canonicalize(xml_bytes):
        """
        تحويل XML إلى C14N (Canonical Form)
        """
        root = etree.fromstring(xml_bytes)
        return etree.tostring(root, method="c14n")

    @staticmethod
    def sign_xml(xml_bytes, private_key):
        """
        توقيع XML باستخدام ECDSA SHA256
        """
        canonical_xml = XMLSigner.canonicalize(xml_bytes)

        signature = private_key.sign(
            canonical_xml,
            ec.ECDSA(hashes.SHA256())
        )

        return base64.b64encode(signature).decode("utf-8")
