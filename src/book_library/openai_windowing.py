"""Lightweight full-library OpenAI windows with exact Unicode source offsets.

The frozen pilot retains its original E5 tokenizer. This versioned contract is
for new full-library OpenAI indexes only, and requires neither model weights nor
the optional transformers stack.
"""
from __future__ import annotations

from bisect import bisect_left, bisect_right
import json

from . import semantic as provider

TOKENIZER = 'tiktoken:cl100k_base'
REVISION = 'reading-room-cl100k-v1'
MAX_TOKENS = 512
OVERLAP = 40


def config():
    return {'cache_version': 3, 'engine': 'openai', 'model': provider.OPENAI_MODEL,
            'model_revision': provider.OPENAI_MODEL, 'dimensions': provider.OPENAI_DIMENSIONS,
            'normalization': 'unit-l2', 'metric': 'cos', 'passage_prefix': '', 'query_prefix': '',
            'window_tokenizer': TOKENIZER, 'window_tokenizer_revision': REVISION,
            'window_max_tokens': MAX_TOKENS}


def encoding():
    import tiktoken
    return tiktoken.get_encoding('cl100k_base')


def encode(tokenizer, text):
    # Source text is data: strings resembling special tokens stay literal.
    return tokenizer.encode(text, disallowed_special=())


def source_offsets(tokenizer, text):
    """Map token byte spans outward to whole Unicode code points, never decode slices."""
    boundaries = [0]
    for char in text:
        boundaries.append(boundaries[-1] + len(char.encode('utf-8')))
    offsets = []
    byte_offset = 0
    for token in encode(tokenizer, text):
        end = byte_offset + len(tokenizer.decode_single_token_bytes(token))
        offsets.append((bisect_right(boundaries, byte_offset) - 1, bisect_left(boundaries, end)))
        byte_offset = end
    if byte_offset != boundaries[-1]:
        raise ValueError('Tokenizer byte offsets did not preserve the source text.')
    return offsets


def segments(cache, tokenizer, title, heading, text):
    signature = provider.canonical_hash({'title': title, 'heading': heading, 'text': text, 'windowing': REVISION})
    saved = cache.execute('SELECT segments FROM segmentation WHERE signature=?', (signature,)).fetchone()
    if saved:
        return json.loads(saved[0])
    header = title + ' · ' + heading
    tokens = encode(tokenizer, header)
    if len(tokens) > 96:
        # Only the artificial metadata header is abbreviated. Source offsets
        # always refer to slices of the unchanged extracted passage.
        header = b''.join(tokenizer.decode_single_token_bytes(token) for token in tokens[:90]).decode('utf-8', errors='ignore')
    room = MAX_TOKENS - len(encode(tokenizer, header + '\n')) - 12
    offsets = source_offsets(tokenizer, text)
    result = []
    start = 0
    while start < len(offsets):
        end = min(start + room, len(offsets))
        a, b = offsets[start][0], offsets[end - 1][1]
        value = header + '\n' + text[a:b]
        while len(encode(tokenizer, value)) > MAX_TOKENS:
            end -= 1
            if end <= start:
                raise ValueError('A source segment cannot fit the OpenAI window limit.')
            b = offsets[end - 1][1]
            value = header + '\n' + text[a:b]
        result.append({'text': value, 'char_start': a, 'char_end': b,
                       'token_count': len(encode(tokenizer, value))})
        if end == len(offsets):
            break
        start = max(start + 1, end - OVERLAP)
    cache.execute('INSERT OR REPLACE INTO segmentation VALUES(?,?)', (signature, json.dumps(result, ensure_ascii=False)))
    return result


def legacy_tokenizer(config):
    """Load only a pinned tokenizer, retaining legacy window text and cache keys."""
    revision = config.get('window_tokenizer_revision')
    import re
    if not isinstance(revision, str) or not re.fullmatch(r'[a-f0-9]{40,64}', revision):
        raise ValueError('The legacy window tokenizer needs its original pinned revision; no automatic reindex was started.')
    try:
        from transformers import AutoTokenizer
    except ImportError:
        raise ValueError("This existing index uses legacy E5 windows. Install only its tokenizer support with .venv/bin/python -m pip install -e '.[legacy-tokenizer]' before extending or rebuilding it. Existing OpenAI search still works; no automatic reembedding was started.") from None
    try:
        return AutoTokenizer.from_pretrained(provider.LOCAL_MODEL, revision=revision, trust_remote_code=False)
    except (OSError, ImportError):
        raise ValueError('The pinned legacy tokenizer is unavailable. Install the legacy-tokenizer extra and allow its public tokenizer assets to download, then retry. Existing indexes and paid caches are retained.') from None
