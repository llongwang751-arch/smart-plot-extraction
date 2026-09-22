/** 60 行手写 Markdown 渲染：标题 / 加粗 / 斜体 / 行内代码 / 列表 / 表格 / 引用 / 分割线 / 链接。
 *  刻意不引入 markdown 库；所有原始文本先转义再拼接，杜绝 XSS。
 */

const escape = (s) =>
  String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')

function inline(raw) {
  return escape(raw)
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/(^|[^*])\*([^*\n]+)\*/g, '$1<em>$2</em>')
    .replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>')
}

function table(rows) {
  const cells = (line) => line.replace(/^\s*\|/, '').replace(/\|\s*$/, '').split('|').map((c) => c.trim())
  const isSep = (line) => /-/.test(line) && /^[\s|:-]+$/.test(line)
  const parsed = rows.map(cells)
  const head = parsed[0] || []
  const body = parsed.slice(1).filter((_, i) => !isSep(rows[i + 1]))
  return (
    `<table><thead><tr>${head.map((h) => `<th>${inline(h)}</th>`).join('')}</tr></thead>` +
    `<tbody>${body.map((r) => `<tr>${r.map((c) => `<td>${inline(c)}</td>`).join('')}</tr>`).join('')}</tbody></table>`
  )
}

export function renderMarkdown(src) {
  const text = String(src || '').replace(/\r\n?/g, '\n')
  if (!text.trim()) return ''
  const lines = text.split('\n')
  const out = []
  let list = null
  let para = []

  const flushPara = () => {
    if (para.length) out.push(`<p>${inline(para.join(' '))}</p>`)
    para = []
  }
  const flushList = () => {
    if (list) out.push(`<${list.tag}>${list.items.map((i) => `<li>${inline(i)}</li>`).join('')}</${list.tag}>`)
    list = null
  }
  const flush = () => {
    flushPara()
    flushList()
  }

  for (let i = 0; i < lines.length; i += 1) {
    const line = lines[i].trim()
    if (!line) {
      flush()
      continue
    }
    if (line.startsWith('|') && line.endsWith('|')) {
      const rows = []
      while (i < lines.length && lines[i].trim().startsWith('|')) {
        rows.push(lines[i].trim())
        i += 1
      }
      i -= 1
      flush()
      out.push(table(rows))
      continue
    }
    const title = line.match(/^(#{1,4})\s+(.*)$/)
    if (title) {
      flush()
      const n = title[1].length
      out.push(`<h${n}>${inline(title[2])}</h${n}>`)
      continue
    }
    if (/^(-{3,}|\*{3,})$/.test(line)) {
      flush()
      out.push('<hr>')
      continue
    }
    const quote = line.match(/^>\s?(.*)$/)
    if (quote) {
      flush()
      out.push(`<blockquote>${inline(quote[1])}</blockquote>`)
      continue
    }
    const ul = line.match(/^[-*+]\s+(.*)$/)
    if (ul) {
      flushPara()
      if (!list || list.tag !== 'ul') {
        flushList()
        list = { tag: 'ul', items: [] }
      }
      list.items.push(ul[1])
      continue
    }
    const ol = line.match(/^\d+[.)]\s+(.*)$/)
    if (ol) {
      flushPara()
      if (!list || list.tag !== 'ol') {
        flushList()
        list = { tag: 'ol', items: [] }
      }
      list.items.push(ol[1])
      continue
    }
    flushList()
    para.push(line)
  }
  flush()
  return out.join('\n')
}

export default renderMarkdown
