import base64
from datetime import datetime

class QRGenerator:

    @staticmethod
    def _tlv(tag, value):
        value_bytes = value.encode('utf-8')
        return bytes([tag, len(value_bytes)]) + value_bytes

    @staticmethod
    def generate_qr(seller_name, vat_number, invoice_datetime, total_with_vat, vat_amount, xml_hash=None, signature=None, public_key=None, certificate_signature=None):
        """
        إنشاء QR Code متوافق مع ZATCA TLV Base64
        """

        tlv_data = b""

        tlv_data += QRGenerator._tlv(1, seller_name)
        tlv_data += QRGenerator._tlv(2, vat_number)
        tlv_data += QRGenerator._tlv(3, invoice_datetime.isoformat())
        tlv_data += QRGenerator._tlv(4, str(total_with_vat))
        tlv_data += QRGenerator._tlv(5, str(vat_amount))
        if xml_hash:
            tlv_data += QRGenerator._tlv(6, xml_hash)
        if signature:
            tlv_data += QRGenerator._tlv(7, signature)
        if public_key:
            tlv_data += QRGenerator._tlv(8, public_key)
        if certificate_signature:
            tlv_data += QRGenerator._tlv(9, certificate_signature)

        return base64.b64encode(tlv_data).decode('utf-8')
