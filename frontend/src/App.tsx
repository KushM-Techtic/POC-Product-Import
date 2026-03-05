import './App.css'
import React, { useState } from 'react'
import {
  Card,
  Form,
  Input,
  InputNumber,
  Select,
  Button,
  Upload,
  Table,
  Modal,
  Checkbox,
  Space,
  Typography,
  message,
  Alert,
} from 'antd'
import type { UploadFile, UploadProps } from 'antd'
import { EditOutlined, UploadOutlined } from '@ant-design/icons'

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
  const [searchMethod, setSearchMethod] = useState<'tavily' | 'openai'>('tavily')
  const [isUploading, setIsUploading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [status, setStatus] = useState<string | null>(null)
  const [products, setProducts] = useState<Product[]>([])
  const [isExporting, setIsExporting] = useState(false)
  const [editIndex, setEditIndex] = useState<number | null>(null)
  const [editForm, setEditForm] = useState<Product | null>(null)
  const [imagePreviewUrl, setImagePreviewUrl] = useState<string | null>(null)

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
    onRemove: () => {
      setFile(null)
      setFileList([])
    },
  }

  const runProcess = async () => {
    if (!file) {
      message.error('Please choose an Excel file first.')
      return
    }
    setIsUploading(true)
    setError(null)
    setStatus('Processing… fetching product data for review.')
    setProducts([])
    try {
      const formData = new FormData()
      formData.append('file', file)
      formData.append('max_products', String(maxProducts || 5))
      formData.append('search_method', searchMethod)
      formData.append('preview_only', 'true')

      const response = await fetch(`${apiBase}/upload`, {
        method: 'POST',
        body: formData,
      })

      if (!response.ok) {
        const text = await response.text()
        throw new Error(text || `Upload failed with status ${response.status}`)
      }

      const data = await response.json()
      const list: Product[] = Array.isArray(data.products) ? data.products : []
      setProducts(list.map((p: Product) => ({ ...p, _approved: false })))
      setStatus(`Loaded ${list.length} product(s). Review, edit if needed, approve, then export or import to BigCommerce.`)
      message.success(`Loaded ${list.length} product(s).`)
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Something went wrong.'
      setError(msg)
      setStatus(null)
      message.error(msg)
    } finally {
      setIsUploading(false)
    }
  }

  const updateProduct = (index: number, field: keyof Product, value: string | number | boolean | string[] | undefined) => {
    setProducts((prev) => {
      const next = [...prev]
      const p = { ...next[index], [field]: value }
      if (field === 'image_url' && typeof value === 'string') {
        p._image_urls = [value]
      }
      next[index] = p
      return next
    })
  }

  const setApproved = (index: number, approved: boolean) => {
    updateProduct(index, '_approved', approved)
  }

  const openEditModal = (index: number) => {
    const p = products[index]
    setEditForm({ ...p })
    setEditIndex(index)
  }

  const closeEditModal = () => {
    setEditIndex(null)
    setEditForm(null)
  }

  const saveEditModal = () => {
    if (editIndex === null || editForm === null) return
    setProducts((prev) => {
      const next = [...prev]
      const saved = { ...editForm }
      if (saved.image_url) saved._image_urls = [saved.image_url]
      next[editIndex] = saved
      return next
    })
    message.success('Product updated.')
    closeEditModal()
  }

  const updateEditForm = (field: keyof Product, value: string | number | boolean | string[] | undefined) => {
    setEditForm((prev) => (prev ? { ...prev, [field]: value } : null))
  }

  const approveAll = () => {
    setProducts((prev) => prev.map((p) => ({ ...p, _approved: true })))
    message.info('All products approved.')
  }

  const approvedProducts = products.filter((p) => p._approved)
  const canExport = approvedProducts.length > 0

  const buildPayload = () =>
    approvedProducts.map((p) => {
      const { _approved, ...rest } = p
      const out = { ...rest }
      if (!out._image_urls && out.image_url) out._image_urls = [out.image_url]
      return out
    })

  const doDownloadExcel = async () => {
    if (!canExport) {
      message.warning('Approve at least one product first.')
      return
    }
    setIsExporting(true)
    setError(null)
    setStatus('Generating Excel…')
    try {
      const response = await fetch(`${apiBase}/export`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ products: buildPayload(), import_to_bigcommerce: false }),
      })
      if (!response.ok) {
        const text = await response.text()
        throw new Error(text || `Export failed with status ${response.status}`)
      }
      const blob = await response.blob()
      const disposition = response.headers.get('Content-Disposition') || ''
      const match = disposition.match(/filename="?([^"]+)"?/)
      const filename = match?.[1] || 'bigcommerce_export.xlsx'
      const url = window.URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = filename
      document.body.appendChild(a)
      a.click()
      a.remove()
      window.URL.revokeObjectURL(url)
      setStatus('Excel file downloaded.')
      message.success('Excel downloaded.')
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Export failed.'
      setError(msg)
      setStatus(null)
      message.error(msg)
    } finally {
      setIsExporting(false)
    }
  }

  const doImportToBigCommerce = async () => {
    if (!canExport) {
      message.warning('Approve at least one product first.')
      return
    }
    setIsExporting(true)
    setError(null)
    setStatus('Importing to BigCommerce…')
    try {
      const response = await fetch(`${apiBase}/import-to-bigcommerce`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ products: buildPayload() }),
      })
      if (!response.ok) {
        const text = await response.text()
        throw new Error(text || `Import failed with status ${response.status}`)
      }
      const data = await response.json()
      const imported = data?.products_imported ?? 0
      const imagesSet = data?.images_set ?? 0
      const errCount = (data?.errors ?? []).length
      setStatus(`BigCommerce: ${imported} product(s) imported, ${imagesSet} image(s) set${errCount ? `, ${errCount} error(s)` : ''}.`)
      message.success(`Imported ${imported} product(s) to BigCommerce.`)
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Import failed.'
      setError(msg)
      setStatus(null)
      message.error(msg)
    } finally {
      setIsExporting(false)
    }
  }

  const columns = [
    {
      title: 'Approve',
      key: 'approve',
      width: 80,
      render: (_: unknown, __: Product, index: number) => (
        <Checkbox
          checked={!!products[index]?._approved}
          onChange={(e) => setApproved(index, e.target.checked)}
        />
      ),
    },
    {
      title: 'Brand',
      dataIndex: 'brand_name',
      key: 'brand_name',
      width: 100,
      ellipsis: true,
      render: (v: string) => v ?? '—',
    },
    {
      title: 'SKU',
      key: 'sku',
      width: 100,
      ellipsis: true,
      render: (_: unknown, r: Product) => String(r.sku ?? r.sku_raw ?? '—'),
    },
    {
      title: 'Name',
      dataIndex: 'name',
      key: 'name',
      width: 140,
      ellipsis: true,
      render: (v: string) => v ?? '—',
    },
    {
      title: 'Price',
      dataIndex: 'price',
      key: 'price',
      width: 80,
      render: (v: string | number) => v ?? '—',
    },
    {
      title: 'Description',
      dataIndex: 'description',
      key: 'description',
      ellipsis: true,
      render: (v: string) => (v && v.length > 60 ? `${v.slice(0, 60)}…` : (v ?? '—')),
    },
    {
      title: 'Image',
      dataIndex: 'image_url',
      key: 'image_url',
      width: 80,
      render: (v: string) =>
        v && v.startsWith('http') ? (
          <span
            role="button"
            tabIndex={0}
            className="table-product-img-wrap"
            onClick={() => setImagePreviewUrl(v)}
            onKeyDown={(e) => e.key === 'Enter' && setImagePreviewUrl(v)}
          >
            <img src={v} alt="" className="table-product-img" referrerPolicy="no-referrer" />
          </span>
        ) : (
          <span className="table-no-img">—</span>
        ),
    },
    {
      title: 'Source',
      key: 'source',
      width: 120,
      ellipsis: true,
      render: (_: unknown, r: Product) =>
        [r._search_method, (r.source_website ?? '').slice(0, 30)].filter(Boolean).join(' · ') || '—',
    },
    {
      title: 'Actions',
      key: 'actions',
      width: 80,
      fixed: 'right' as const,
      render: (_: unknown, __: Product, index: number) => (
        <Button type="link" size="small" icon={<EditOutlined />} onClick={() => openEditModal(index)} aria-label="Edit">
          Edit
        </Button>
      ),
    },
  ]

  return (
    <div className="app">
      <Typography.Title level={3} style={{ marginBottom: 4 }}>AI BigCommerce Export</Typography.Title>
      <Typography.Paragraph type="secondary" style={{ marginBottom: 24 }}>
        Upload Excel → review and edit results in the table → approve → download Excel or import to BigCommerce.
      </Typography.Paragraph>

      <Card>
        <Form layout="vertical" onFinish={runProcess}>
          <Form.Item label="Source Excel file (.xlsx or .xls)" name="file" required>
            <Upload {...uploadProps}>
              <Button icon={<UploadOutlined />} disabled={isUploading}>Select file</Button>
            </Upload>
          </Form.Item>

          <Space wrap size="middle">
            <Form.Item label="Max products" name="maxProducts" initialValue={5}>
              <InputNumber
                min={1}
                max={100}
                value={maxProducts}
                onChange={(v) => setMaxProducts(v ?? 5)}
                disabled={isUploading}
              />
            </Form.Item>
            {/* Hidden: always use tavily; still sent to backend */}
            <Form.Item label="Search method" name="searchMethod" initialValue="tavily" style={{ display: 'none' }}>
              <Select
                style={{ width: 220 }}
                value={searchMethod}
                onChange={setSearchMethod}
                disabled={isUploading}
                options={[
                  { value: 'tavily', label: 'Tavily (search + extract)' },
                  { value: 'openai', label: 'OpenAI web search' },
                ]}
              />
            </Form.Item>
          </Space>

          <Form.Item>
            <Button type="primary" htmlType="submit" loading={isUploading} disabled={!file}>
              {isUploading ? 'Processing…' : 'Process & Review'}
            </Button>
          </Form.Item>
        </Form>

        {status && <Alert type="success" message={status} showIcon style={{ marginBottom: 16 }} />}
        {error && <Alert type="error" message={error} showIcon style={{ marginBottom: 16 }} />}

        {products.length > 0 && (
          <>
            <Space style={{ marginBottom: 16 }}>
              <Button onClick={approveAll}>Approve all</Button>
              <Button type="primary" onClick={doDownloadExcel} disabled={!canExport || isExporting} loading={isExporting}>
                Download Excel
              </Button>
              <Button type="primary" onClick={doImportToBigCommerce} disabled={!canExport || isExporting} loading={isExporting}>
                Import to BigCommerce
              </Button>
            </Space>
            <Typography.Text type="secondary" style={{ display: 'block', marginBottom: 8 }}>
              Click Edit in the Actions column to change any field. Check Approve to include in Excel / BigCommerce.
            </Typography.Text>
            <Table
              rowKey={(_, i) => String(i)}
              columns={columns}
              dataSource={products}
              pagination={{ pageSize: 10 }}
              scroll={{ x: 900 }}
              size="small"
            />
          </>
        )}

        <Typography.Title level={5} style={{ marginTop: 24, marginBottom: 8 }}>How it works</Typography.Title>
        <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
          <ul style={{ paddingLeft: 20, margin: 0 }}>
            <li>Click &quot;Process & Review&quot; to run AI column mapping and product enrichment.</li>
            <li>Table shows results; click Edit in the Actions column to open the edit modal and change any field.</li>
            <li>Check &quot;Approve&quot; for products to include, then &quot;Download Excel&quot; or &quot;Import to BigCommerce&quot;.</li>
          </ul>
        </Typography.Paragraph>
      </Card>

      <Modal
        title="Edit product"
        open={editForm !== null}
        onCancel={closeEditModal}
        onOk={saveEditModal}
        okText="Save"
        cancelText="Cancel"
        width={520}
        destroyOnClose
        bodyStyle={{ maxHeight: '70vh', overflowY: 'auto' }}
      >
        {editForm !== null && (
          <Space direction="vertical" style={{ width: '100%' }} size="middle">
            <Form layout="vertical" size="small">
              <Form.Item label="Brand name">
                <Input
                  value={String(editForm.brand_name ?? '')}
                  onChange={(e) => updateEditForm('brand_name', e.target.value)}
                />
              </Form.Item>
              <Form.Item label="SKU">
                <Input
                  value={String(editForm.sku ?? editForm.sku_raw ?? '')}
                  onChange={(e) => {
                    updateEditForm('sku', e.target.value)
                    updateEditForm('sku_raw', e.target.value)
                  }}
                />
              </Form.Item>
              <Form.Item label="Name">
                <Input
                  value={String(editForm.name ?? '')}
                  onChange={(e) => updateEditForm('name', e.target.value)}
                />
              </Form.Item>
              <Form.Item label="Price">
                <Input
                  value={String(editForm.price ?? '')}
                  onChange={(e) => updateEditForm('price', e.target.value)}
                />
              </Form.Item>
              <Form.Item label="Description">
                <Input.TextArea
                  value={String(editForm.description ?? '')}
                  onChange={(e) => updateEditForm('description', e.target.value)}
                  rows={4}
                />
              </Form.Item>
              <Form.Item label="Image URL">
                <Input
                  value={String(editForm.image_url ?? '')}
                  onChange={(e) => updateEditForm('image_url', e.target.value)}
                />
                {editForm.image_url && editForm.image_url.startsWith('http') && (
                  <div className="edit-modal-img-preview">
                    <img src={editForm.image_url} alt="Preview" referrerPolicy="no-referrer" />
                  </div>
                )}
              </Form.Item>
              <Form.Item label="Source website">
                <Input
                  value={String(editForm.source_website ?? '')}
                  onChange={(e) => updateEditForm('source_website', e.target.value)}
                />
              </Form.Item>
              <Form.Item>
                <Checkbox
                  checked={!!editForm._approved}
                  onChange={(e) => updateEditForm('_approved', e.target.checked)}
                >
                  Approve (include in export/import)
                </Checkbox>
              </Form.Item>
            </Form>
          </Space>
        )}
      </Modal>

      <Modal
        title="Image preview"
        open={!!imagePreviewUrl}
        onCancel={() => setImagePreviewUrl(null)}
        footer={null}
        width={480}
        styles={{ body: { padding: 16, textAlign: 'center' } }}
      >
        {imagePreviewUrl && (
          <img src={imagePreviewUrl} alt="Preview" className="image-preview-large" referrerPolicy="no-referrer" />
        )}
      </Modal>
    </div>
  )
}

export default App
