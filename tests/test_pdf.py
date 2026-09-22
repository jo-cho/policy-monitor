import unittest
from io import BytesIO
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
from pdf_support import extract_pdfs, PDFInputError

def fixture_pdf(lines, password=None):
    # 실제 PDF 바이트를 메모리에서 만들어 텍스트 추출 경로를 검사합니다.
    writer = PdfWriter()
    for line in lines:
        page = writer.add_blank_page(width=600, height=800)
        if line:
            font = DictionaryObject({NameObject('/Type'): NameObject('/Font'),
                NameObject('/Subtype'): NameObject('/Type1'), NameObject('/BaseFont'): NameObject('/Helvetica')})
            page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): font})})
            stream = DecodedStreamObject()
            stream.set_data(f'BT /F1 12 Tf 50 700 Td ({line}) Tj ET'.encode('ascii'))
            page[NameObject('/Contents')] = stream
    if password:
        writer.encrypt(password)
    data = BytesIO()
    writer.write(data)
    return data.getvalue()


class PolicyPDFTests(unittest.TestCase):
    def test_real_pdf_pages_and_ocr_failure(self):
        docs = [{'name':'policy.pdf', 'data':fixture_pdf(['The policy grant is 100 units for each applicant.', ''])}]
        pages, failures, total = extract_pdfs(docs)
        self.assertEqual(total, 2)
        self.assertEqual(pages[0]['page_number'], 1)
        self.assertIn('100', pages[0]['text'])
        self.assertEqual(failures[0]['page_number'], 2)

    def test_invalid_file_rejected(self):
        with self.assertRaises(PDFInputError):
            extract_pdfs([{'name':'broken.pdf', 'data':b'invalid'}])
