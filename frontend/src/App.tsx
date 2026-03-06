import './App.css'
import { useState } from 'react'
import { InputNumber, Button, Upload, Table, Modal, Checkbox, message, Progress } from 'antd'
import type { UploadFile, UploadProps } from 'antd'
import {
  EditOutlined,
  CloudUploadOutlined,
  CheckCircleOutlined,
  FileExcelOutlined,
  ShoppingOutlined,
  ThunderboltOutlined,
  PictureOutlined,
  SafetyCertificateOutlined,
  LinkOutlined,
  TagOutlined,
  DollarOutlined,
  BarcodeOutlined,
  GlobalOutlined,
  CloseCircleOutlined,
  CheckOutlined,
  InboxOutlined,
} from '@ant-design/icons'

type Product = {
  brand_name?: string
  sku?: string
  sku_raw?: string
  name?: string
  price?: string | number
  description?: string
  image_url?: string
  _image_urls?: string[]
  source_website?: string
  _search_method?: string
  raw_row?: Record<string, unknown>
  _approved?: boolean
}

const apiBase = (import.meta.env.VITE_API_BASE_URL as string | undefined) || ''

function App() {
  const [file, setFile] = useState<File | null>(null)
  const [fileList, setFileList] = useState<UploadFile[]>([])
  const [maxProducts, setMaxProducts] = useState<number>(5)
  const [isUploading, setIsUploading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [status, setStatus] = useState<string | null>(null)
  const [products, setProducts] = useState<Product[]>([])
  const [isExporting, setIsExporting] = useState(false)
  const [editIndex, setEditIndex] = useState<number | null>(null)
  const [editForm, setEditForm] = useState<Product | null>(null)
  const [galleryImages, setGalleryImages] = useState<string[]>([])
  const [galleryIndex, setGalleryIndex] = useState(0)
  const [galleryProductIndex, setGalleryProductIndex] = useState<number | null>(null)

  const uploadProps: UploadProps = {
    accept: '.xlsx,.xls',
    maxCount: 1,
    fileList,
    beforeUpload: (f) => {
      setFile(f)
      setFileList([{ uid: '-1', name: f.name, status: 'done', originFileObj: f }])
      setError(null)
      setStatus(null)
      setProducts([])
      return false
    },
    onRemove: () => { setFile(null); setFileList([]) },
  }

  const runProcess = async () => {
    if (!file) { message.error('Please choose an Excel file first.'); return }
    setIsUploading(true)
    setError(null)
    setStatus('Processing…')
    setProducts([])
    try {
      const fd = new FormData()
      fd.append('file', file)
      fd.append('max_products', String(maxProducts || 5))
      fd.append('search_method', 'tavily')
      fd.append('preview_only', 'true')
      const res = await fetch(`${apiBase}/upload`, { method: 'POST', body: fd })
      if (!res.ok) throw new Error((await res.text()) || `Status ${res.status}`)
      const data = await res.json()
      const list: Product[] = Array.isArray(data.products) ? data.products : []
      setProducts(list.map((p: Product) => ({ ...p, _approved: false })))
      setStatus(`${list.length} products loaded. Review and approve below.`)
      message.success(`${list.length} products loaded.`)
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Something went wrong.'
      setError(msg); setStatus(null); message.error(msg)
    } finally { setIsUploading(false) }
  }

  const updateProduct = (index: number, field: keyof Product, value: string | number | boolean | string[] | undefined) => {
    setProducts((prev) => {
      const next = [...prev]
      const p = { ...next[index], [field]: value }
      if (field === 'image_url' && typeof value === 'string' && Array.isArray(p._image_urls)) {
        const urls = p._image_urls.filter((u) => u !== value)
        p._image_urls = [value, ...urls]
      } else if (field === 'image_url' && typeof value === 'string') {
        p._image_urls = [value]
      }
      next[index] = p
      return next
    })
  }

  const setMainImageFromGallery = (productIndex: number, newMainUrl: string, allUrls: string[]) => {
    const reordered = [newMainUrl, ...allUrls.filter((u) => u !== newMainUrl)]
    setProducts((prev) => {
      const next = [...prev]
      next[productIndex] = { ...next[productIndex], image_url: newMainUrl, _image_urls: reordered }
      return next
    })
  }

  const validateForApproval = (p: Product) => {
    const missing: string[] = []
    if (!String(p.sku ?? p.sku_raw ?? '').trim()) missing.push('SKU')
    if (!String(p.name ?? '').trim()) missing.push('Name')
    if (!String(p.price ?? '').trim()) missing.push('Price')
    const img = String(p.image_url ?? '').trim()
    if (!img || !img.startsWith('http')) missing.push('Image')
    return { ok: missing.length === 0, missing }
  }

  const setApproved = (index: number, approved: boolean) => {
    if (approved) {
      const v = validateForApproval(products[index] ?? {})
      if (!v.ok) { message.warning(`Cannot approve — missing: ${v.missing.join(', ')}`); return }
    }
    updateProduct(index, '_approved', approved)
  }

  const openEditModal = (index: number) => {
    if (products[index]?._approved) { message.info('Un-approve this product first to edit.'); return }
    setEditForm({ ...products[index] })
    setEditIndex(index)
  }

  const closeEditModal = () => { setEditIndex(null); setEditForm(null) }

  const saveEditModal = () => {
    if (editIndex === null || editForm === null) return
    setProducts((prev) => {
      const next = [...prev]
      const saved = { ...editForm }
      if (saved.image_url) {
        const urls = saved._image_urls ?? []
        const main = saved.image_url
        const others = urls.filter((u) => u !== main)
        saved._image_urls = [main, ...others]
      }
      next[editIndex] = saved
      return next
    })
    message.success('Product saved.')
    closeEditModal()
  }

  const updateEditForm = (field: keyof Product, value: string | number | boolean | string[] | undefined) =>
    setEditForm((prev) => (prev ? { ...prev, [field]: value } : null))

  const openGallery = (product: Product, index: number) => {
    const imgs = (product._image_urls ?? []).filter((u) => u?.startsWith('http'))
    if (imgs.length === 0 && product.image_url?.startsWith('http')) imgs.push(product.image_url)
    if (imgs.length === 0) return
    setGalleryImages(imgs); setGalleryIndex(0); setGalleryProductIndex(index)
  }

  const approveAll = () => {
    let ok = 0, skip = 0
    setProducts((prev) => prev.map((p) => {
      if (!validateForApproval(p).ok) { skip++; return { ...p, _approved: false } }
      ok++; return { ...p, _approved: true }
    }))
    if (skip) message.warning(`Approved ${ok}, skipped ${skip} (missing data).`)
    else message.success(`All ${ok} products approved.`)
  }

  const unapproveAll = () => {
    setProducts((prev) => prev.map((p) => ({ ...p, _approved: false })))
    message.info('All products un-approved.')
  }

  const approvedProducts = products.filter((p) => p._approved)
  const canExport = approvedProducts.length > 0

  const buildPayload = () => approvedProducts.map((p) => {
    const { _approved, ...rest } = p
    const out = { ...rest }
    if (!out._image_urls && out.image_url) out._image_urls = [out.image_url]
    return out
  })

  const doDownloadExcel = async () => {
    if (!canExport) { message.warning('Approve at least one product first.'); return }
    setIsExporting(true); setError(null); setStatus('Generating Excel…')
    try {
      const res = await fetch(`${apiBase}/export`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ products: buildPayload(), import_to_bigcommerce: false }),
      })
      if (!res.ok) throw new Error((await res.text()) || `Status ${res.status}`)
      const blob = await res.blob()
      const fname = (res.headers.get('Content-Disposition') || '').match(/filename="?([^"]+)"?/)?.[1] || 'bigcommerce_export.xlsx'
      const a = document.createElement('a')
      a.href = window.URL.createObjectURL(blob); a.download = fname
      document.body.appendChild(a); a.click(); a.remove()
      window.URL.revokeObjectURL(a.href)
      setStatus('Excel downloaded.'); message.success('Excel downloaded.')
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Export failed.'
      setError(msg); setStatus(null); message.error(msg)
    } finally { setIsExporting(false) }
  }

  const doImportToBigCommerce = async () => {
    if (!canExport) { message.warning('Approve at least one product first.'); return }
    setIsExporting(true); setError(null); setStatus('Importing to BigCommerce…')
    try {
      const res = await fetch(`${apiBase}/import-to-bigcommerce`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ products: buildPayload() }),
      })
      if (!res.ok) throw new Error((await res.text()) || `Status ${res.status}`)
      const data = await res.json()
      const imp = data?.products_imported ?? 0
      const imgs = data?.images_set ?? 0
      const errs = (data?.errors ?? []).length
      setStatus(`BigCommerce: ${imp} product(s) imported, ${imgs} image(s) set${errs ? `, ${errs} error(s)` : ''}.`)
      message.success(`${imp} product(s) imported to BigCommerce.`)
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Import failed.'
      setError(msg); setStatus(null); message.error(msg)
    } finally { setIsExporting(false) }
  }

  const pct = products.length ? Math.round((approvedProducts.length / products.length) * 100) : 0

  const columns = [
    {
      title: '',
      key: 'approve',
      width: 52,
      render: (_: unknown, __: Product, index: number) => (
        <Checkbox
          checked={!!products[index]?._approved}
          onChange={(e) => setApproved(index, e.target.checked)}
          className="approve-checkbox"
        />
      ),
    },
    {
      title: 'Image',
      key: 'img',
      width: 72,
      render: (_: unknown, r: Product, index: number) => {
        const v = r.image_url
        const count = (r._image_urls ?? []).filter((u) => u?.startsWith('http')).length
        return v?.startsWith('http') ? (
          <span className="table-img-wrap" role="button" tabIndex={0}
            onClick={() => openGallery(r, index)}
            onKeyDown={(e) => e.key === 'Enter' && openGallery(r, index)}>
            <img src={v} alt="" className="table-img" referrerPolicy="no-referrer" />
            {count > 1 && <span className="img-badge">+{count - 1}</span>}
          </span>
        ) : <span className="no-img"><PictureOutlined /></span>
      },
    },
    {
      title: 'Product',
      key: 'product',
      render: (_: unknown, r: Product) => (
        <div className="cell-product">
          <div className="cell-name">{r.name || '—'}</div>
          <div className="cell-meta">
            <span className="meta-tag"><BarcodeOutlined /> {r.sku ?? r.sku_raw ?? '—'}</span>
            <span className="meta-tag"><TagOutlined /> {r.brand_name ?? '—'}</span>
          </div>
        </div>
      ),
    },
    {
      title: 'Price',
      key: 'price',
      width: 90,
      render: (_: unknown, r: Product) => (
        <span className="cell-price">{r.price ? `$${r.price}` : '—'}</span>
      ),
    },
    {
      title: 'Description',
      dataIndex: 'description',
      key: 'description',
      ellipsis: true,
      render: (v: string) => <span className="cell-desc">{v && v.length > 70 ? `${v.slice(0, 70)}…` : (v || '—')}</span>,
    },
    {
      title: 'Status',
      key: 'status',
      width: 110,
      render: (_: unknown, __: Product, index: number) => {
        const approved = products[index]?._approved
        return (
          <span className={`status-badge ${approved ? 'status-approved' : 'status-pending'}`}>
            {approved ? <><CheckCircleOutlined /> Approved</> : <><CloseCircleOutlined /> Pending</>}
          </span>
        )
      },
    },
    {
      title: 'Actions',
      key: 'actions',
      width: 90,
      fixed: 'right' as const,
      render: (_: unknown, __: Product, index: number) => (
        <button
          className={`edit-btn ${products[index]?._approved ? 'edit-btn-disabled' : ''}`}
          onClick={() => openEditModal(index)}
          disabled={!!products[index]?._approved}
          title={products[index]?._approved ? 'Un-approve to edit' : 'Edit product'}
        >
          <EditOutlined />
        </button>
      ),
    },
  ]

  const step = products.length > 0 ? 2 : 1

  return (
    <div className="layout">
      {/* Sidebar */}
      <aside className="sidebar">
        <div className="sidebar-logo">
          <div className="logo-icon"><ThunderboltOutlined /></div>
          <span className="logo-text">ProductAI</span>
        </div>
        <nav className="sidebar-nav">
          <div className={`nav-item ${step >= 1 ? 'nav-active' : ''}`}>
            <span className={`nav-step-dot ${step >= 1 ? 'dot-done' : ''}`}>1</span>
            <span>Upload</span>
          </div>
          <div className="nav-connector" />
          <div className={`nav-item ${step >= 2 ? 'nav-active' : ''}`}>
            <span className={`nav-step-dot ${step >= 2 ? 'dot-done' : ''}`}>2</span>
            <span>Review</span>
          </div>
          <div className="nav-connector" />
          <div className={`nav-item ${canExport ? 'nav-active' : ''}`}>
            <span className={`nav-step-dot ${canExport ? 'dot-done' : ''}`}>3</span>
            <span>Export</span>
          </div>
        </nav>
        <div className="sidebar-footer">
          <div className="sidebar-help">
            <SafetyCertificateOutlined />
            <span>AI-powered enrichment</span>
          </div>
          <div className="sidebar-help">
            <GlobalOutlined />
            <span>Tavily web search</span>
          </div>
        </div>
      </aside>

      {/* Main */}
      <main className="main">
        {/* Top bar */}
        <header className="topbar">
          <div className="topbar-title">
            <h1>Product Import</h1>
            <p>Upload an Excel file to AI-enrich products and export to BigCommerce</p>
          </div>
          {products.length > 0 && (
            <div className="topbar-stats">
              <div className="stat-card stat-total">
                <span className="stat-num">{products.length}</span>
                <span className="stat-label">Total</span>
              </div>
              <div className="stat-card stat-approved">
                <span className="stat-num">{approvedProducts.length}</span>
                <span className="stat-label">Approved</span>
              </div>
              <div className="stat-card stat-pending">
                <span className="stat-num">{products.length - approvedProducts.length}</span>
                <span className="stat-label">Pending</span>
              </div>
            </div>
          )}
        </header>

        {/* Upload section */}
        <section className="section">
          <div className="section-header">
            <span className="section-step">01</span>
            <h2>Upload & Process</h2>
          </div>
          <div className="upload-card">
            <Upload {...uploadProps} className="drop-zone">
              <div className="drop-content">
                <div className="drop-icon-wrap">
                  <InboxOutlined className="drop-icon" />
                </div>
                <p className="drop-title">
                  {file ? file.name : 'Drop your Excel file here'}
                </p>
                <p className="drop-sub">
                  {file ? 'File ready — click Process & review below' : 'or click to browse  •  .xlsx / .xls'}
                </p>
                {file && <span className="drop-check"><CheckOutlined /> File selected</span>}
              </div>
            </Upload>
            <div className="upload-controls">
              <div className="control-group">
                <label className="control-label">Max products to process</label>
                <InputNumber
                  min={1} max={100} value={maxProducts}
                  onChange={(v) => setMaxProducts(v ?? 5)}
                  disabled={isUploading}
                  className="num-input"
                />
              </div>
              <Button
                type="primary"
                size="large"
                onClick={runProcess}
                loading={isUploading}
                disabled={!file}
                icon={<ThunderboltOutlined />}
                className="btn-primary"
              >
                {isUploading ? 'Processing…' : 'Process & review'}
              </Button>
            </div>

            {isUploading && (
              <div className="processing-bar">
                <div className="processing-label">
                  <ThunderboltOutlined /> AI is searching and enriching product data…
                </div>
                <Progress percent={100} status="active" showInfo={false} strokeColor={{ from: '#6366f1', to: '#06b6d4' }} />
              </div>
            )}
            {status && !isUploading && (
              <div className="msg-success"><CheckCircleOutlined /> {status}</div>
            )}
            {error && (
              <div className="msg-error"><CloseCircleOutlined /> {error}</div>
            )}
          </div>
        </section>

        {/* Results section */}
        {products.length > 0 && (
          <section className="section">
            <div className="section-header">
              <span className="section-step">02</span>
              <h2>Review & Approve</h2>
              <span className="section-hint">Click an image to preview all • Click Edit to modify • Approve to include in export</span>
            </div>

            {/* Progress + actions toolbar */}
            <div className="results-toolbar">
              <div className="approve-progress-wrap">
                <span className="pct-label">{pct}% approved</span>
                <Progress
                  percent={pct} showInfo={false} size={[240, 8]}
                  strokeColor={{ from: '#10b981', to: '#6366f1' }}
                />
              </div>
              <div className="toolbar-btns">
                <button className="toolbar-btn btn-outline" onClick={approveAll}>
                  <CheckCircleOutlined /> Approve all
                </button>
                <button className="toolbar-btn btn-ghost" onClick={unapproveAll}>
                  <CloseCircleOutlined /> Un-approve all
                </button>
                <button
                  className={`toolbar-btn btn-excel ${!canExport || isExporting ? 'btn-disabled' : ''}`}
                  onClick={doDownloadExcel}
                  disabled={!canExport || isExporting}
                >
                  <FileExcelOutlined /> Download Excel
                </button>
                <button
                  className={`toolbar-btn btn-bc ${!canExport || isExporting ? 'btn-disabled' : ''}`}
                  onClick={doImportToBigCommerce}
                  disabled={!canExport || isExporting}
                >
                  <ShoppingOutlined /> Import to BigCommerce
                </button>
              </div>
            </div>

            <div className="table-wrap">
              <Table
                rowKey={(_, i) => String(i)}
                columns={columns}
                dataSource={products}
                pagination={{ pageSize: 10, showSizeChanger: true, showTotal: (t) => `${t} products` }}
                scroll={{ x: 900 }}
                size="middle"
                className="product-table"
                rowClassName={(_, i) => (products[i]?._approved ? 'row-approved' : 'row-pending')}
              />
            </div>
          </section>
        )}

        {/* How it works */}
        <section className="how-section">
          <h3 className="how-title">How it works</h3>
          <div className="how-steps">
            {[
              { icon: <CloudUploadOutlined />, label: 'Upload', text: 'Upload your Excel file — any column naming.' },
              { icon: <ThunderboltOutlined />, label: 'AI Enrichment', text: 'AI maps columns, searches web, fills missing data and images.' },
              { icon: <CheckCircleOutlined />, label: 'Review', text: 'Review results, edit any field, and approve products.' },
              { icon: <ShoppingOutlined />, label: 'Export', text: 'Download BigCommerce Excel or import directly via API.' },
            ].map((s, i) => (
              <div className="how-step" key={i}>
                <div className="how-icon">{s.icon}</div>
                <div className="how-label">{s.label}</div>
                <div className="how-text">{s.text}</div>
              </div>
            ))}
          </div>
        </section>
      </main>

      {/* Edit Modal */}
      <Modal
        centered
        title={
          <div className="modal-title">
            <EditOutlined />
            <span>Edit Product</span>
            <span className="modal-sku">{editForm?.sku ?? editForm?.sku_raw ?? ''}</span>
          </div>
        }
        open={editForm !== null}
        onCancel={closeEditModal}
        onOk={saveEditModal}
        okText="Save changes"
        cancelText="Cancel"
        width={580}
        destroyOnClose
        className="edit-modal"
        styles={{ body: { maxHeight: '72vh', overflowY: 'auto', padding: '16px 24px' } }}
      >
        {editForm !== null && (
          <div className="edit-form">
            <div className="form-row">
              <div className="form-group">
                <label><BarcodeOutlined /> SKU</label>
                <input className="form-input" value={String(editForm.sku ?? editForm.sku_raw ?? '')}
                  onChange={(e) => { updateEditForm('sku', e.target.value); updateEditForm('sku_raw', e.target.value) }} />
              </div>
              <div className="form-group">
                <label><TagOutlined /> Brand</label>
                <input className="form-input" value={String(editForm.brand_name ?? '')}
                  onChange={(e) => updateEditForm('brand_name', e.target.value)} />
              </div>
            </div>
            <div className="form-group">
              <label><SafetyCertificateOutlined /> Product name</label>
              <input className="form-input" value={String(editForm.name ?? '')}
                onChange={(e) => updateEditForm('name', e.target.value)} />
            </div>
            <div className="form-row">
              <div className="form-group">
                <label><DollarOutlined /> Price</label>
                <input className="form-input" value={String(editForm.price ?? '')}
                  onChange={(e) => updateEditForm('price', e.target.value)} />
              </div>
              <div className="form-group">
                <label><GlobalOutlined /> Source website</label>
                <input className="form-input" value={String(editForm.source_website ?? '')}
                  onChange={(e) => updateEditForm('source_website', e.target.value)} />
              </div>
            </div>
            <div className="form-group">
              <label>Description</label>
              <textarea className="form-textarea" rows={4} value={String(editForm.description ?? '')}
                onChange={(e) => updateEditForm('description', e.target.value)} />
            </div>
            <div className="form-group">
              <label><LinkOutlined /> Main image URL</label>
              <input className="form-input" value={String(editForm.image_url ?? '')}
                onChange={(e) => updateEditForm('image_url', e.target.value)} />
              {editForm.image_url?.startsWith('http') && (
                <div className="edit-img-preview">
                  <img src={editForm.image_url} alt="Preview" referrerPolicy="no-referrer" />
                </div>
              )}
            </div>
            {(() => {
              const imgs = (editForm._image_urls ?? []).filter((u) => u?.startsWith('http'))
              if (imgs.length <= 1) return null
              return (
                <div className="form-group">
                  <label><PictureOutlined /> All images — click to set as main</label>
                  <div className="img-grid">
                    {imgs.map((url, i) => (
                      <div key={i} className={`img-thumb ${editForm.image_url === url ? 'thumb-active' : ''}`}
                        role="button" tabIndex={0}
                        onClick={() => updateEditForm('image_url', url)}
                        onKeyDown={(e) => e.key === 'Enter' && updateEditForm('image_url', url)}>
                        <img src={url} alt={`img-${i}`} referrerPolicy="no-referrer" />
                        {editForm.image_url === url && <span className="thumb-badge">Main</span>}
                      </div>
                    ))}
                  </div>
                </div>
              )
            })()}
            <div className="form-approve">
              <label className="approve-label">
                <input type="checkbox" checked={!!editForm._approved}
                  onChange={(e) => updateEditForm('_approved', e.target.checked)} />
                <span>Approve this product for export / import</span>
              </label>
            </div>
          </div>
        )}
      </Modal>

      {/* Gallery Modal */}
      <Modal
        centered
        title={
          <div className="modal-title">
            <PictureOutlined />
            <span>Product Images</span>
            <span className="modal-sku">{galleryIndex + 1} / {galleryImages.length}</span>
          </div>
        }
        open={galleryImages.length > 0}
        onCancel={() => { setGalleryImages([]); setGalleryProductIndex(null) }}
        footer={
          galleryProductIndex !== null ? (
            <Button type="primary" className="btn-primary"
              onClick={() => {
                setMainImageFromGallery(galleryProductIndex, galleryImages[galleryIndex], galleryImages)
                message.success('Main image updated.')
              }}
              disabled={!!products[galleryProductIndex]?._approved}
              icon={<CheckOutlined />}>
              Set as main image
            </Button>
          ) : null
        }
        width={620}
        className="gallery-modal"
        styles={{ body: { padding: 16 } }}
      >
        {galleryImages.length > 0 && (
          <div className="gallery-body">
            <div className="gallery-main">
              <img src={galleryImages[galleryIndex]} alt="" className="gallery-img" referrerPolicy="no-referrer" />
            </div>
            {galleryImages.length > 1 && (
              <div className="gallery-strip">
                {galleryImages.map((url, i) => (
                  <div key={i} className={`gallery-thumb ${i === galleryIndex ? 'gallery-thumb-active' : ''}`}
                    role="button" tabIndex={0}
                    onClick={() => setGalleryIndex(i)}
                    onKeyDown={(e) => e.key === 'Enter' && setGalleryIndex(i)}>
                    <img src={url} alt="" referrerPolicy="no-referrer" />
                    {i === galleryIndex && <span className="thumb-badge">Viewing</span>}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </Modal>
    </div>
  )
}

export default App
