"""FunASR tokenizer adaptation for non-ASCII Windows model-cache paths."""

from pathlib import Path


def register_memory_tokenizer() -> str:
    import sentencepiece
    from funasr.register import tables
    from funasr.tokenizer.sentencepiece_tokenizer import SentencepiecesTokenizer

    name = "ProjectMemorySentencepiecesTokenizer"
    if name not in tables.tokenizer_classes:
        @tables.register("tokenizer_classes", name)
        class MemorySentencepiecesTokenizer(SentencepiecesTokenizer):
            def _build_sentence_piece_processor(self):
                if self.sp is None:
                    # SentencePiece's native file opener fails on some Windows
                    # Unicode paths. Python's file API handles them correctly.
                    self.sp = sentencepiece.SentencePieceProcessor(
                        model_proto=Path(self.bpemodel).read_bytes())

    return name
