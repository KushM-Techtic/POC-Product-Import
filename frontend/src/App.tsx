import './App.css'
import React, { useState } from 'react'

function App() {
  const [file, setFile] = useState<File | null>(null)
  const [maxProducts, setMaxProducts] = useState<number>(5)
  const [searchMethod, setSearchMethod] = useState<'tavily' | 'openai'>('tavily')
  const [isUploading, setIsUploading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [status, setStatus] = useState<string | null>(null)
  const [importToBigCommerce, setImportToBigCommerce] = useState(false)

  const apiBase =
    (import.meta.env.VITE_API_BASE_URL as string | undefined) || 'http://localhost:8000'

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0] || null
    setFile(f)
    setError(null)
    setStatus(null)
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!file) {
      setError('Please choose an Excel file first.')
      return
    }
    setIsUploading(true)
    setError(null)
    setStatus('Uploading and processing…')
    try {
      const formData = new FormData()
      formData.append('file', file)
      formData.append('max_products', String(maxProducts || 5))
      formData.append('search_method', searchMethod)
      formData.append('import_to_bigcommerce', importToBigCommerce ? 'true' : 'false')

      const response = await fetch(`${apiBase}/upload`, {
        method: 'POST',
        body: formData,
      })

      if (!response.ok) {
        const text = await response.text()
        throw new Error(text || `Upload failed with status ${response.status}`)
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

      setStatus('Done. Excel file downloaded.')
    } catch (err: any) {
      console.error(err)
      setError(err?.message || 'Something went wrong.')
      setStatus(null)
    } finally {
      setIsUploading(false)
    }
  }

  return (
    <div className="app">
      <header className="app-header">
        <h1>AI BigCommerce Export</h1>
        <p>Upload your source Excel and let the backend create a cleaned BigCommerce file.</p>
      </header>

      <main className="card">
        <form onSubmit={handleSubmit} className="form">
          <div className="form-row">
            <label htmlFor="file">Source Excel file (.xlsx or .xls)</label>
            <input
              id="file"
              type="file"
              accept=".xlsx,.xls"
              onChange={handleFileChange}
              disabled={isUploading}
            />
          </div>

          <div className="form-row-inline">
            <div className="form-field">
              <label htmlFor="maxProducts">Max products</label>
              <input
                id="maxProducts"
                type="number"
                min={1}
                max={100}
                value={maxProducts}
                onChange={(e) => setMaxProducts(Number(e.target.value) || 5)}
                disabled={isUploading}
              />
            </div>

            <div className="form-field">
              <label htmlFor="searchMethod">Search method</label>
              <select
                id="searchMethod"
                value={searchMethod}
                onChange={(e) => setSearchMethod(e.target.value as 'tavily' | 'openai')}
                disabled={isUploading}
              >
                <option value="tavily">Tavily (search + extract)</option>
                <option value="openai">OpenAI web search</option>
              </select>
            </div>
          </div>

          <div className="form-row">
            <label className="checkbox-row">
              <input
                type="checkbox"
                checked={importToBigCommerce}
                onChange={(e) => setImportToBigCommerce(e.target.checked)}
                disabled={isUploading}
              />
              <span>Also import products directly into BigCommerce (via API)</span>
            </label>
          </div>

          <button type="submit" disabled={isUploading || !file}>
            {isUploading
              ? importToBigCommerce
                ? 'Processing and importing…'
                : 'Processing…'
              : importToBigCommerce
              ? 'Generate Excel + Import to BigCommerce'
              : 'Generate BigCommerce Excel'}
          </button>
        </form>

        {status && <p className="status">{status}</p>}
        {error && <p className="error">{error}</p>}

        <section className="help">
          <h2>How it works</h2>
          <ul>
            <li>The backend AI maps your columns to the fixed schema.</li>
            <li>It enriches up to N products via web search (Tavily or OpenAI).</li>
            <li>You get a ready‑to‑upload BigCommerce Excel file with images and source website.</li>
          </ul>
        </section>
      </main>
    </div>
  )
}

export default App
