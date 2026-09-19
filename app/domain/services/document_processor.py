import os
import re
import unicodedata
from typing import Dict, List

from langchain.docstore.document import Document
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.document_loaders import PyPDFLoader, TextLoader


class DocumentProcessor:
    def __init__(self, chunk_size: int = 1024, chunk_overlap: int = 256):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap
        )

    def preprocess_text(self, text: str) -> str:
        """Limpa e normaliza o texto."""
        text = text.lower()
        text = unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode('utf-8')
        text = re.sub(r'[^\w\s.,!?-]', ' ', text)
        return " ".join(text.split())

    def process_file(self, file_path: str) -> List[Dict]:
        """
        Método principal que carrega e divide um arquivo em chunks com base na sua extensão.

        Só faz o parsing/chunking -- NAO indexa no Qdrant. Antes, este
        método tinha seu próprio upsert direto (`self.qdrant_client`),
        com collection_name, formato de ponto e embedding (literalmente
        `np.random.rand` -- nunca chegou a chamar um modelo real)
        completamente divorciados do pipeline real de indexação
        (`QdrantVectorStore.save`, chamado por `script/run_ingestion.py`
        logo depois deste método retornar). Esse código morto sempre
        lançava exceção (`chunk_id` como string não é um point ID
        válido no Qdrant atual), impedindo a ingestão de terminar em
        qualquer ambiente. Removido -- os chunks retornados aqui já são
        o que `run_ingestion.py` persiste de verdade.
        """
        file_extension = os.path.splitext(file_path)[1].lower()

        if file_extension == ".pdf":
            loader = PyPDFLoader(file_path)
        elif file_extension in [".md", ".txt"]:
            loader = TextLoader(file_path, encoding='utf-8')
        else:
            print(f"⚠️  Tipo de arquivo não suportado: {file_extension}. Pulando.")
            return []

        documents = loader.load()
        return self._create_small_to_big_chunks(documents, file_path)

    def _create_small_to_big_chunks(self, documents: List[Document], file_path: str) -> List[Dict]:
        """
        Processa uma lista de documentos carregados e os divide em chunks "Small-to-Big".
        """
        chunks_with_metadata = []
        file_name = os.path.basename(file_path)

        for doc in documents:
            parent_content = self.preprocess_text(doc.page_content)
            child_chunks = self.splitter.split_text(parent_content)

            # Para PDFs, doc.metadata['page'] existe. Para .md/.txt, definimos como 1.
            page_number = doc.metadata.get("page", 0) + 1

            for idx, child_chunk in enumerate(child_chunks):
                chunks_with_metadata.append({
                    "child_text": child_chunk,       # O texto "filho" a ser embedado
                    "parent_text": parent_content,   # O texto "pai" para o contexto
                    "metadata": {
                        "source": file_name,
                        "page": page_number,
                        "chunk_id": f"page_{page_number}_chunk_{idx}"
                    }
                })
        return chunks_with_metadata