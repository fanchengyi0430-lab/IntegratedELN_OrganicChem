"""Export a case as a static Word notebook and a one-line-per-record index."""
import datetime
import os
from pathlib import Path
import re
import struct
import tempfile
from xml.sax.saxutils import escape, quoteattr
import zipfile

from .store import StoreError, is_screening
from . import formatting, si_format

_XML = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
_WORD = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
_DRAW = 'http://schemas.openxmlformats.org/drawingml/2006/'
_OFFICE = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
_PACKAGE = 'http://schemas.openxmlformats.org/package/2006/'
_WIDTH = 9360  # Letter minus two one-inch margins, in twips
_HEIGHT = 12960
_EMU_PER_TWIP = 635
_JPEG_FRAMES = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}
_BASIS = 'basis not stated'


class NotebookLocked(OSError):
    """The destination Word file could not be replaced."""


def _text(value):
    if value is None:
        return ''
    return re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]', '', str(value))


def _joined(values, separator=' · '):
    return separator.join(text for value in values if (text := _text(value)))


def _p(value='', style='', bold=False, page_break=False, formatted=None):
    props = (f'<w:pStyle w:val="{style}"/>' if style else '') + ('<w:pageBreakBefore/>' if page_break else '')
    props = f'<w:pPr>{props}</w:pPr>' if props else ''
    lines = _text(value).replace('\r\n', '\n').replace('\r', '\n').split('\n')
    parts = []
    for i, line in enumerate(lines):
        if i:
            parts.append('<w:r><w:br/></w:r>')
        for kind, text in (formatted if formatted is not None else formatting.chemical(line)):
            emphasis = '<w:b/>' if bold else ''
            if kind in ('sub', 'sup'):
                align = 'subscript' if kind == 'sub' else 'superscript'
                emphasis += f'<w:vertAlign w:val="{align}"/>'
            if kind == 'i':
                emphasis += '<w:i/>'
            rpr = f'<w:rPr>{emphasis}</w:rPr>' if emphasis else ''
            parts.append(f'<w:r>{rpr}<w:t xml:space="preserve">{escape(_text(text))}</w:t></w:r>')
    return f'<w:p>{props}{"".join(parts)}</w:p>'


def _table(headers, widths, rows):
    parts = [f'<w:tbl><w:tblPr><w:tblStyle w:val="TableGrid"/><w:tblW w:w="{sum(widths)}" w:type="dxa"/>'
             '<w:tblLayout w:type="fixed"/></w:tblPr><w:tblGrid>']
    parts.extend(f'<w:gridCol w:w="{width}"/>' for width in widths)
    parts.append('</w:tblGrid>')
    for i, row in enumerate([headers, *rows]):
        parts.append('<w:tr><w:trPr><w:tblHeader/></w:trPr>' if i == 0 else '<w:tr>')
        for width, value in zip(widths, row):
            parts.append(f'<w:tc><w:tcPr><w:tcW w:w="{width}" w:type="dxa"/></w:tcPr>{_p(value, bold=i == 0)}</w:tc>')
        parts.append('</w:tr>')
    parts.append('</w:tbl>')
    return ''.join(parts)


def _styles():
    normal = ('<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/>'
              '<w:pPr><w:spacing w:after="100"/></w:pPr><w:rPr><w:sz w:val="22"/></w:rPr></w:style>')
    styles = [normal]
    for style, name, size, outline in (('Title', 'Title', 44, ''), ('Heading1', 'heading 1', 32, '0'),
                                       ('Heading2', 'heading 2', 26, '1')):
        level = f'<w:outlineLvl w:val="{outline}"/>' if outline else ''
        styles.append(f'<w:style w:type="paragraph" w:styleId="{style}"><w:name w:val="{name}"/>'
                      '<w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/><w:pPr>'
                      f'<w:keepNext/><w:spacing w:before="180" w:after="120"/>{level}</w:pPr>'
                      f'<w:rPr><w:b/><w:sz w:val="{size}"/></w:rPr></w:style>')
    borders = ''.join(f'<w:{edge} w:val="single" w:sz="4" w:color="888888"/>'
                      for edge in ('top', 'left', 'bottom', 'right', 'insideH', 'insideV'))
    styles.append('<w:style w:type="table" w:styleId="TableGrid"><w:name w:val="Table Grid"/>'
                  f'<w:tblPr><w:tblBorders>{borders}</w:tblBorders></w:tblPr></w:style>')
    return f'<w:styles xmlns:w="{_WORD}">{"".join(styles)}</w:styles>'


def _relationships(entries):
    items = ''.join(f'<Relationship Id="{rid}" Type="{_OFFICE}/{kind}" Target={quoteattr(target)}/>'
                    for rid, kind, target in entries)
    return f'<Relationships xmlns="{_PACKAGE}relationships">{items}</Relationships>'


def _content_types(media):
    formats = {'rels': 'application/vnd.openxmlformats-package.relationships+xml', 'xml': 'application/xml'}
    for name, _ in media:
        suffix = name.rsplit('.', 1)[1]
        formats[suffix] = 'image/' + suffix
    defaults = ''.join(f'<Default Extension="{ext}" ContentType="{kind}"/>' for ext, kind in formats.items())
    mimes = 'application/vnd.openxmlformats-officedocument.wordprocessingml.'
    return (f'<Types xmlns="{_PACKAGE}content-types">{defaults}'
            f'<Override PartName="/word/document.xml" ContentType="{mimes}document.main+xml"/>'
            f'<Override PartName="/word/styles.xml" ContentType="{mimes}styles+xml"/></Types>')


def _image_size(data, ext):
    if ext == 'png':
        if len(data) >= 24 and data[:16] == b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR':
            return struct.unpack_from('>II', data, 16)
    elif data.startswith(b'\xff\xd8'):
        pos = 2
        while pos + 4 <= len(data) and data[pos] == 0xFF:
            pos += 1
            if data[pos] == 0xFF:
                continue
            marker = data[pos]
            if marker in (0xD9, 0xDA):  # end of image or start of compressed scan
                break
            length = struct.unpack_from('>H', data, pos + 1)[0]
            if length < 2 or pos + length >= len(data):
                break
            if marker in _JPEG_FRAMES and length >= 7:
                height, width = struct.unpack_from('>HH', data, pos + 4)
                return width, height
            pos += length + 1
    return 0, 0


def _drawing(number, name, description, size):
    width, height = size
    # Fill the available width when the aspect ratio fits within the page height.
    cx = min(_WIDTH * _EMU_PER_TWIP, _HEIGHT * _EMU_PER_TWIP * width // height)
    cy = cx * height // width
    size = f'cx="{max(1, cx)}" cy="{max(1, cy)}"'
    return ('<w:p><w:r><w:drawing><wp:inline>'
            f'<wp:extent {size}/><wp:docPr id="{number}" name={quoteattr(name)} descr={quoteattr(description)}/>'
            '<a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">'
            f'<pic:pic><pic:nvPicPr><pic:cNvPr id="{number}" name={quoteattr(name)}/><pic:cNvPicPr/></pic:nvPicPr>'
            f'<pic:blipFill><a:blip r:embed="rId{number + 1}"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>'
            f'<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext {size}/></a:xfrm>'
            '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr></pic:pic></a:graphicData></a:graphic>'
            '</wp:inline></w:drawing></w:r></w:p>')


def _scheme(layout, rec, media):
    name = rec.get('scheme_image')
    if not name:
        return ''
    ext = Path(name).suffix.lower()
    if ext not in ('.png', '.jpg', '.jpeg'):
        return _p('Scheme file · ' + name)
    ext = 'png' if ext == '.png' else 'jpeg'
    try:
        path = layout.case_file(layout.asset(rec["id"], name))
        data = path.read_bytes()
    except (StoreError, ValueError, OSError, RuntimeError):
        return _p('Scheme image unavailable · ' + name)
    size = _image_size(data, ext)
    if not all(size):
        return _p('Scheme image unavailable · ' + name)
    number = len(media) + 1
    media.append((f'media/scheme{number}.{ext}', data))
    return _drawing(number, _text(Path(name).name), _text(rec.get('scheme_alt') or name), size)


def _description(value):
    if isinstance(value, dict):
        return _joined((_joined((k, _description(v)), ' — ') for k, v in value.items()))
    if isinstance(value, list):
        return _joined(_description(v) for v in value)
    return value


def _materials(materials):
    fields = (('name', 'Material', 1800), ('formula', 'Formula', 1050), ('mw', 'MW', 720),
              ('equiv', 'Equiv', 640), ('mmol', 'mmol', 640), ('amount', 'Amount', 1100),
              ('assay', 'Assay (wt%)', 760), ('density', 'Density (g/mL)', 830), ('bottle', 'Bottle', 1820))
    return _table([header for _, header, _ in fields], [width for _, _, width in fields],
                  [[_description(m.get(key)) for key, _, _ in fields] for m in materials])


def _section(parts, title, lines):
    parts.append(_p(title, 'Heading2'))
    parts.extend(_p(line) for line in lines)


def _experiment(layout, rec, media, page_break):
    parts = [_p(_joined((rec['id'], rec.get('title')), ' — '), 'Heading1', page_break=page_break)]
    dates = ('Started ' + _text(rec['started']) if rec.get('started') else '',
             'Ended ' + _text(rec['ended']) if rec.get('ended') else '')
    parts.extend((_p(_joined((rec.get('type'), rec.get('status'), *dates, rec.get('researcher')))),
                  _p(rec.get('question'))))
    if is_screening(rec):
        metric = _joined((rec.get('metric_kind'), rec.get('metric')), ' — ')
        parts.append(_p('Primary metric · ' + (metric or 'Unspecified')))
    parts.append(_scheme(layout, rec, media))
    if rec.get('materials'):
        parts.extend((_p('Materials', 'Heading2'), _materials(rec['materials'])))
    if rec.get('conditions'):
        parts.append(_p(rec['conditions']))
    if rec.get('procedure'):
        _section(parts, 'Procedure', [*rec['procedure'], rec.get('procedure_basis') or _BASIS])
    if rec.get('runs'):
        rows = []
        for run in rec['runs']:
            result = _text(run.get('result'))
            if run.get('measured') is not None:
                measured = run['measured']
                value = measured.get('value') if isinstance(measured, dict) else measured
                result = _joined((result, 'Measured ' + _text(value) + '%'), '\n')
            rows.append([run.get('run'), run.get('variable'), result, run.get('basis') or _BASIS])
        parts.extend((_p('Runs', 'Heading2'), _table(('Run', 'Conditions', 'Result', 'Basis'), (800, 2950, 1400, 4210), rows),
                      _p(rec.get('results_basis') or _BASIS)))
    if rec.get('result'):
        result = rec['result']
        _section(parts, 'Isolated result', (result.get('text'), result.get('basis') or _BASIS))
    if rec.get('characterization'):
        parts.append(_p('Characterization', 'Heading2'))
        lines = sorted((si_format.characterization(x) for x in rec['characterization']), key=lambda line: line[0])
        parts.extend(_p(formatted=runs) for _, runs, _ in lines)
        parts.append(_p(rec.get('characterization_basis') or _BASIS))
    if rec.get('attachments'):
        def attachment_line(item):
            sample = 'Sample ' + _text(item['sample']) if item.get('sample') else ''
            run = 'Run ' + _text(item['run']) if item.get('run') is not None else ''
            return _joined((item.get('kind'), item.get('path'), sample, run, item.get('added'), item.get('by'), item.get('note')))

        _section(parts, 'Attachments', (attachment_line(item) for item in rec['attachments']))
    if rec.get('flags'):
        _section(parts, 'Open flags', (_joined((f.get('tier'), f.get('id'), f.get('text'))) for f in rec['flags']))
    for key, title in (('history', 'History'), ('checks', 'Checks')):
        if rec.get(key):
            _section(parts, title, rec[key])
    for key, title in (('entries', 'Notebook entries'), ('sources', 'Sources')):
        if rec.get(key):
            _section(parts, title, (_joined((k, _description(v)), ' — ') for k, v in rec[key].items()))
    return ''.join(parts)


def _document(layout, title, cfg, records, media):
    parts = [_p(title, 'Title')]
    if cfg.get('researcher'):
        parts.append(_p(cfg['researcher']))
    if cfg.get('project_question'):
        _section(parts, 'Project question', [cfg['project_question']])
    if cfg.get('caveats'):
        _section(parts, 'Shared caveats', cfg['caveats'])
    parts.append(_p('Built ' + datetime.date.today().isoformat()))
    parts.extend(_experiment(layout, rec, media, i == 0) for i, rec in enumerate(records))
    parts.append('<w:sectPr><w:pgSz w:w="12240" w:h="15840"/>'
                 '<w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440" '
                 'w:header="720" w:footer="720" w:gutter="0"/></w:sectPr>')
    return (f'<w:document xmlns:w="{_WORD}" xmlns:r="{_OFFICE}" xmlns:wp="{_DRAW}wordprocessingDrawing" '
            f'xmlns:a="{_DRAW}main" xmlns:pic="{_DRAW}picture"><w:body>{"".join(parts)}</w:body></w:document>')


def _index(title, caveats, records):
    def line(value):
        return ' '.join(_text(value).splitlines())

    lines = ['# ' + line(title), '']
    keys = ('id', 'status', 'type', 'title', 'key_result')
    lines.extend('- ' + ' · '.join(line(rec.get(key)) for key in keys) for rec in records)
    if caveats:
        lines.extend(('', '## Shared caveats', ''))
        lines.extend('- ' + line(item) for item in caveats)
    return '\n'.join(lines) + '\n'


def export(case):
    """Write both exports from one ordered snapshot of the case's records."""
    root = case.layout.root
    cfg = case.cfg()
    title = cfg.get('title') or case.name
    name = cfg.get('notebook', 'notebook.docx')
    if not isinstance(name, str) or Path(name).suffix.lower() != '.docx':
        raise ValueError('Choose a .docx file name in case.yaml.')
    notebook = case.layout.case_file(name)
    if notebook.suffix.lower() != '.docx':
        raise ValueError('Choose a .docx file name in case.yaml.')
    records = [case.read(rid)[0] for rid in case.ids()]
    media = []
    document = _document(case.layout, title, cfg, records, media)
    relationships = [('rId1', 'styles', 'styles.xml')]
    relationships.extend((f'rId{i}', 'image', name) for i, (name, _) in enumerate(media, start=2))
    parts = {'[Content_Types].xml': _content_types(media),
             '_rels/.rels': _relationships([('rId1', 'officeDocument', 'word/document.xml')]),
             'word/document.xml': document, 'word/styles.xml': _styles(),
             'word/_rels/document.xml.rels': _relationships(relationships)}
    with tempfile.TemporaryDirectory(prefix='.export-', dir=root) as temp:
        word_stage = Path(temp) / 'notebook.docx'
        index_stage = Path(temp) / 'index.md'
        with zipfile.ZipFile(word_stage, 'w') as archive:
            for part, xml in parts.items():
                archive.writestr(zipfile.ZipInfo(part), _XML + xml, compress_type=zipfile.ZIP_DEFLATED)
            for part, data in media:
                archive.writestr(zipfile.ZipInfo('word/' + part), data, compress_type=zipfile.ZIP_DEFLATED)
        index_stage.write_bytes(_index(title, cfg.get('caveats'), records).encode('utf-8'))
        try:
            os.replace(word_stage, notebook)
        except PermissionError as exc:
            raise NotebookLocked from exc
        os.replace(index_stage, case.layout.index)
    return 'Wrote index.md and ' + notebook.name + '.'
