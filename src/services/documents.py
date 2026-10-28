from pathlib import Path
import pandas as pd
import pypdf
from langchain_text_splitters import (
    MarkdownHeaderTextSplitter,
    RecursiveCharacterTextSplitter,
)
from langchain_core.documents import Document


def parse_and_chunk_document(doc_path: Path) -> list[Document]:
    ext = doc_path.suffix.lower()
    raw_chunks: list[Document] = []
    text_splitter = RecursiveCharacterTextSplitter(chunk_size=600, chunk_overlap=60)

    if ext == ".md":
        headers_to_split_on = [
            ("#", "Header_1"),
            ("##", "Header_2"),
            ("###", "Header_3"),
        ]
        md_splitter = MarkdownHeaderTextSplitter(
            headers_to_split_on=headers_to_split_on
        )
        raw_text = doc_path.read_text(encoding="utf-8")
        header_docs = md_splitter.split_text(raw_text)
        raw_chunks = text_splitter.split_documents(header_docs)

    elif ext == ".txt":
        raw_text = doc_path.read_text(encoding="utf-8")
        raw_docs = [Document(page_content=raw_text)]
        raw_chunks = text_splitter.split_documents(raw_docs)

    elif ext == ".pdf":
        pdf_docs = []
        try:
            with open(doc_path, "rb") as f:
                reader = pypdf.PdfReader(f)
                for page_num, page in enumerate(reader.pages):
                    page_text = page.extract_text()
                    if page_text and page_text.strip():
                        pdf_docs.append(
                            Document(
                                page_content=page_text,
                                metadata={"page_number": page_num + 1},
                            )
                        )
            raw_chunks = text_splitter.split_documents(pdf_docs)
        except Exception:
            raise ValueError(f"Could not parse PDF: {doc_path.name}") from None

    elif ext in [".csv", ".xlsx"]:
        try:
            df = pd.read_csv(doc_path) if ext == ".csv" else pd.read_excel(doc_path)
        except Exception:
            raise ValueError(f"Could not parse table: {doc_path.name}") from None

        for idx, row in df.iterrows():
            row_dict = row.to_dict()
            row_items = [
                f"{str(col)}: {str(val)}"
                for col, val in row_dict.items()
                if pd.notna(val) and str(val).strip() != ""
            ]

            if row_items:
                row_text = " | ".join(row_items)
                doc_item = Document(
                    page_content=row_text, metadata={"row_index": int(idx)}
                )
                raw_chunks.append(doc_item)

    # sanity check
    valid_chunks = []
    for chunk in raw_chunks:
        clean_text = chunk.page_content.strip()
        if clean_text:
            chunk.page_content = clean_text
            valid_chunks.append(chunk)

    return valid_chunks
