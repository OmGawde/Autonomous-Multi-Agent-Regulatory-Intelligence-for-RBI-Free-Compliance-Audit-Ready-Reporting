import React, { useEffect, useState } from 'react';
import { RefreshCw, FileText, Plus, Edit2, Trash2, ExternalLink, X, ChevronLeft, ChevronRight, Save, Sliders } from 'lucide-react';

import { BACKEND_URL } from '../apiConfig';

export default function BanksConfig({ onEditInCalibrator }) {
  const [hashesData, setHashesData] = useState([]);
  const [loading, setLoading] = useState(false);

  // PDF Preview State
  const [viewingPdf, setViewingPdf] = useState(null);
  const [pdfPage, setPdfPage] = useState(0);

  // Modal State for CRUD
  const [showModal, setShowModal] = useState(false);
  const [editingIndex, setEditingIndex] = useState(null); // null = Create, number = Edit
  const [formData, setFormData] = useState({
    bank_name: '',
    sample_file: '',
    x0: '0.0',
    y0: '0.0',
    x1: '1.0',
    y1: '0.3',
    columnsText: 'Date:0.0-0.2, Description:0.2-0.6, Amount:0.6-1.0'
  });

  const fetchHashes = async () => {
    setLoading(true);
    try {
      const response = await fetch(`${BACKEND_URL}/api/bank-hashes`);
      if (response.ok) {
        const data = await response.json();
        setHashesData(Array.isArray(data) ? data : []);
      }
    } catch (error) {
      console.error('Error fetching hashes data:', error);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchHashes();
  }, []);

  const formatCoords = (coords) => {
    if (!coords || typeof coords !== 'object') return 'Not Configured';
    const { x0, y0, x1, y1 } = coords;
    if (x0 === undefined || y0 === undefined) return 'Not Configured';
    return `[${Number(x0).toFixed(3)}, ${Number(y0).toFixed(3)}] to [${Number(x1).toFixed(3)}, ${Number(y1).toFixed(3)}]`;
  };

  // Open Create Modal
  const handleOpenCreate = () => {
    setEditingIndex(null);
    setFormData({
      bank_name: '',
      sample_file: '',
      x0: '0.000',
      y0: '0.000',
      x1: '1.000',
      y1: '0.300',
      columnsText: 'Date:0.0-0.2, Description:0.2-0.6, Balance:0.6-1.0'
    });
    setShowModal(true);
  };

  // Open Edit Modal
  const handleOpenEdit = (bank, index) => {
    setEditingIndex(index);
    const sampleFiles = bank.images?.map((img) => img.original_statement) || [];
    const nameCoords = bank.name_coordinates || {};
    const cols = bank.columns || [];

    const colsStr = cols.map(c => `${c.label}:${c.x0}-${c.x1}`).join(', ');

    setFormData({
      bank_name: bank.bank_name || '',
      sample_file: sampleFiles[0] || '',
      x0: nameCoords.x0 !== undefined ? String(nameCoords.x0) : '0.000',
      y0: nameCoords.y0 !== undefined ? String(nameCoords.y0) : '0.000',
      x1: nameCoords.x1 !== undefined ? String(nameCoords.x1) : '1.000',
      y1: nameCoords.y1 !== undefined ? String(nameCoords.y1) : '0.300',
      columnsText: colsStr
    });
    setShowModal(true);
  };

  // Save Form (Create or Update)
  const handleSaveForm = async (e) => {
    e.preventDefault();
    if (!formData.bank_name.trim()) {
      alert('Bank name is required');
      return;
    }

    // Parse columns text
    const parsedCols = [];
    if (formData.columnsText.trim()) {
      const parts = formData.columnsText.split(',');
      for (let p of parts) {
        const [label, range] = p.split(':');
        if (label && range) {
          const [rx0, rx1] = range.split('-').map(Number);
          if (!isNaN(rx0) && !isNaN(rx1)) {
            parsedCols.push({ label: label.trim(), x0: rx0, x1: rx1 });
          }
        }
      }
    }

    const payload = {
      bank_name: formData.bank_name.trim(),
      images: formData.sample_file ? [{ original_statement: formData.sample_file.trim(), hash: "manual_entry" }] : [],
      name_coordinates: {
        x0: parseFloat(formData.x0) || 0,
        y0: parseFloat(formData.y0) || 0,
        x1: parseFloat(formData.x1) || 1,
        y1: parseFloat(formData.y1) || 0.3
      },
      columns: parsedCols
    };

    try {
      let response;
      if (editingIndex === null) {
        // Create
        response = await fetch(`${BACKEND_URL}/api/bank-hashes/crud`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });
      } else {
        // Update
        response = await fetch(`${BACKEND_URL}/api/bank-hashes/crud/${editingIndex}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });
      }

      if (response.ok) {
        setShowModal(false);
        fetchHashes();
      } else {
        alert('Failed to save registry entry.');
      }
    } catch (err) {
      console.error('Error saving bank hash entry:', err);
    }
  };

  // Delete Registry Entry
  const handleDelete = async (bankName, index) => {
    if (!window.confirm(`Are you sure you want to delete the registry template for "${bankName}"?`)) {
      return;
    }

    try {
      const response = await fetch(`${BACKEND_URL}/api/bank-hashes/crud/${index}`, {
        method: 'DELETE'
      });
      if (response.ok) {
        fetchHashes();
      } else {
        alert('Failed to delete registry entry.');
      }
    } catch (err) {
      console.error('Error deleting registry entry:', err);
    }
  };

  return (
    <div className="view-container">
      <div className="table-card" style={{ maxWidth: '1240px', margin: '0 auto' }}>
        <div className="table-header" style={{ flexWrap: 'wrap', gap: '1rem' }}>
          <div>
            <h3>Calibrated Bank Statement Registries ({hashesData.length})</h3>
            <p className="hide-on-mobile" style={{ fontSize: '0.85rem', color: 'var(--text-muted)', marginTop: '0.25rem' }}>
              Summary of saved PDF image hashes, name region boundaries, and column maps loaded from bank_statement_hashes.json.
            </p>
          </div>
          <div style={{ display: 'flex', gap: '0.75rem' }}>
            <button
              className="header-btn-primary"
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '0.35rem',
                padding: '0.5rem 1rem',
                borderRadius: '0.5rem',
                fontWeight: 700,
                fontSize: '0.85rem',
                cursor: 'pointer'
              }}
              onClick={handleOpenCreate}
            >
              <Plus size={16} />
              <span>+ Add Bank Registry</span>
            </button>

            <button
              className="clear-btn"
              style={{
                background: 'var(--input-bg)',
                color: 'var(--text-main)',
                border: '2px solid #000000',
                display: 'flex',
                alignItems: 'center',
                gap: '0.35rem'
              }}
              onClick={fetchHashes}
            >
              <RefreshCw size={14} className={loading ? 'spin' : ''} />
              <span className="hide-on-mobile">Refresh List</span>
            </button>
          </div>
        </div>

        <div className="data-table-container" style={{ marginTop: '1.5rem' }}>
          {loading ? (
            <div style={{ textAlign: 'center', padding: '4rem', color: 'var(--text-muted)' }}>
              Loading bank registry tables...
            </div>
          ) : hashesData.length === 0 ? (
            <div style={{ textAlign: 'center', padding: '4rem', color: 'var(--text-muted)' }}>
              No calibrated bank hashes registry entries found in database.
            </div>
          ) : (
            <table className="data-table">
              <thead>
                <tr>
                  <th style={{ width: '180px' }}>Bank Name</th>
                  <th style={{ width: '180px' }}>Sample Files</th>
                  <th style={{ width: '140px' }}>Layout Hash</th>
                  <th style={{ width: '200px' }}>Name Coordinates</th>
                  <th>Configured Columns</th>
                  <th style={{ width: '100px', textAlign: 'center' }}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {hashesData.map((bank, index) => {
                  const sampleFiles = bank.images?.map((img) => img.original_statement) || [];
                  const uniqueFiles = Array.from(new Set(sampleFiles));
                  const hashes = bank.images?.map((img) => img.hash) || [];
                  const uniqueHashes = Array.from(new Set(hashes));

                  return (
                    <tr key={index}>
                      <td style={{ fontWeight: 700, color: 'var(--primary)', fontSize: '0.95rem' }}>
                        {bank.bank_name}
                      </td>
                      <td>
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.35rem' }}>
                          {uniqueFiles.length === 0 ? (
                            <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>None</span>
                          ) : (
                            uniqueFiles.map((file, fIdx) => (
                              <button
                                key={fIdx}
                                style={{
                                  background: 'var(--input-bg)',
                                  border: '1.5px solid #000000',
                                  borderRadius: '0.375rem',
                                  padding: '0.25rem 0.5rem',
                                  cursor: 'pointer',
                                  fontSize: '0.8rem',
                                  color: 'var(--text-main)',
                                  display: 'inline-flex',
                                  alignItems: 'center',
                                  gap: '0.35rem',
                                  fontWeight: 600,
                                  transition: 'all 0.2s ease'
                                }}
                                onClick={() => {
                                  setViewingPdf(file);
                                  setPdfPage(0);
                                }}
                                title={`Click to preview ${file}`}
                              >
                                <FileText size={13} color="var(--primary)" />
                                <span>{file}</span>
                                <ExternalLink size={11} style={{ opacity: 0.6 }} />
                              </button>
                            ))
                          )}
                        </div>
                      </td>
                      <td>
                        {uniqueHashes.length === 0 ? (
                          <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>None</span>
                        ) : (
                          <select
                            defaultValue=""
                            style={{
                              background: 'var(--input-bg)',
                              color: 'var(--primary)',
                              fontFamily: 'JetBrains Mono, monospace',
                              border: '1.5px solid #000000',
                              borderRadius: '0.5rem',
                              padding: '0.4rem 0.65rem',
                              fontSize: '0.75rem',
                              fontWeight: 600,
                              cursor: 'pointer',
                              outline: 'none',
                              maxWidth: '180px'
                            }}
                          >
                            <option value="" disabled>
                              {uniqueHashes.length} Hash{uniqueHashes.length > 1 ? 'es' : ''} Saved ▾
                            </option>
                            {uniqueHashes.map((h, hIdx) => (
                              <option key={hIdx} value={h} disabled style={{ color: 'var(--text-main)', fontFamily: 'JetBrains Mono' }}>
                                {h}
                              </option>
                            ))}
                          </select>
                        )}
                      </td>
                      <td>
                        <div
                          style={{
                            fontSize: '0.775rem',
                            fontFamily: 'JetBrains Mono, monospace',
                            color: 'var(--text-main)',
                            background: 'var(--input-bg)',
                            border: '1.5px solid #000000',
                            borderRadius: '0.35rem',
                            padding: '0.35rem 0.6rem',
                            display: 'inline-block'
                          }}
                        >
                          {formatCoords(bank.name_coordinates)}
                        </div>
                      </td>
                      <td>
                        {Array.isArray(bank.columns) && bank.columns.length > 0 ? (
                          <select
                            defaultValue=""
                            style={{
                              background: 'var(--input-bg)',
                              color: 'var(--text-main)',
                              border: '1.5px solid #000000',
                              borderRadius: '0.5rem',
                              padding: '0.4rem 0.65rem',
                              fontSize: '0.8rem',
                              fontWeight: 600,
                              cursor: 'pointer',
                              outline: 'none',
                              maxWidth: '230px'
                            }}
                          >
                            <option value="" disabled>
                              {bank.columns.length} Columns Mapped ▾
                            </option>
                            {bank.columns.map((col, cIdx) => (
                              <option key={cIdx} value={col.label} disabled style={{ color: 'var(--text-main)' }}>
                                {col.label}: {col.x0.toFixed(2)} - {col.x1.toFixed(2)}
                              </option>
                            ))}
                          </select>
                        ) : (
                          <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>None Configured</span>
                        )}
                      </td>
                      <td style={{ textAlign: 'center' }}>
                        <div style={{ display: 'flex', gap: '0.5rem', justifyContent: 'center', alignItems: 'center' }}>
                          <button
                            style={{
                              background: 'var(--input-bg)',
                              border: '1.5px solid #000000',
                              borderRadius: '0.375rem',
                              padding: '0.4rem 0.6rem',
                              cursor: 'pointer',
                              color: 'var(--primary)',
                              display: 'inline-flex',
                              alignItems: 'center',
                              gap: '0.25rem',
                              fontSize: '0.8rem',
                              fontWeight: 600
                            }}
                            onClick={() => handleOpenEdit(bank, index)}
                            title="Edit Bank Registry Entry JSON"
                          >
                            <Edit2 size={14} />
                            <span>Edit</span>
                          </button>

                          <button
                            style={{
                              background: 'rgba(239, 68, 68, 0.1)',
                              border: '1.5px solid #000000',
                              borderRadius: '0.375rem',
                              padding: '0.4rem 0.6rem',
                              cursor: 'pointer',
                              color: 'var(--danger)',
                              display: 'inline-flex',
                              alignItems: 'center',
                              gap: '0.25rem',
                              fontSize: '0.8rem',
                              fontWeight: 600
                            }}
                            onClick={() => handleDelete(bank.bank_name, index)}
                            title="Delete Bank Registry Entry"
                          >
                            <Trash2 size={14} />
                            <span>Delete</span>
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>
      </div>

      {/* PDF Sample Viewer Modal */}
      {viewingPdf && (
        <div className="modal-overlay" onClick={() => setViewingPdf(null)}>
          <div
            className="modal-content"
            style={{ maxWidth: '850px', width: '92%' }}
            onClick={(e) => e.stopPropagation()}
          >
            <div className="modal-header">
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                <FileText size={20} color="var(--primary)" />
                <div>
                  <h3 style={{ fontSize: '1.2rem' }}>Sample PDF Viewer: {viewingPdf}</h3>
                  <p style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>
                    Rendered preview from statement repository
                  </p>
                </div>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                <a
                  href={`${BACKEND_URL}/api/view_pdf?pdf=${encodeURIComponent(viewingPdf)}`}
                  target="_blank"
                  rel="noreferrer"
                  style={{
                    fontSize: '0.8rem',
                    color: 'var(--primary)',
                    fontWeight: 600,
                    textDecoration: 'none',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '0.25rem',
                    background: 'var(--input-bg)',
                    border: '1.5px solid #000000',
                    padding: '0.35rem 0.75rem',
                    borderRadius: '0.5rem'
                  }}
                >
                  Open PDF <ExternalLink size={12} />
                </a>
                <button className="close-modal-btn" onClick={() => setViewingPdf(null)}>
                  <X size={20} />
                </button>
              </div>
            </div>

            <div className="modal-body" style={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
              <div className="page-indicators" style={{ marginBottom: '1rem' }}>
                <button
                  className="page-indicator-btn"
                  disabled={pdfPage === 0}
                  onClick={() => setPdfPage((p) => Math.max(0, p - 1))}
                >
                  <ChevronLeft size={16} />
                </button>
                <span style={{ fontSize: '0.85rem', fontWeight: 600 }}>Page {pdfPage + 1}</span>
                <button
                  className="page-indicator-btn"
                  onClick={() => setPdfPage((p) => p + 1)}
                >
                  <ChevronRight size={16} />
                </button>
              </div>

              <div
                style={{
                  border: '2px solid #000000',
                  borderRadius: '0.75rem',
                  overflow: 'hidden',
                  background: 'var(--code-bg)',
                  boxShadow: 'var(--card-shadow)',
                  maxWidth: '100%'
                }}
              >
                <img
                  src={`${BACKEND_URL}/api/render?pdf=${encodeURIComponent(viewingPdf)}&page=${pdfPage}`}
                  alt={`PDF Page ${pdfPage}`}
                  style={{ maxWidth: '100%', height: 'auto', display: 'block' }}
                  onError={(e) => {
                    e.target.style.display = 'none';
                  }}
                />
              </div>
            </div>
          </div>
        </div>
      )}

      {/* CRUD Create/Edit Modal */}
      {showModal && (
        <div className="modal-overlay" onClick={() => setShowModal(false)}>
          <div
            className="modal-content"
            style={{ maxWidth: '600px', width: '92%' }}
            onClick={(e) => e.stopPropagation()}
          >
            <div className="modal-header">
              <h3>{editingIndex === null ? 'Create Bank Registry Entry' : 'Edit Bank Registry Entry'}</h3>
              <button className="close-modal-btn" onClick={() => setShowModal(false)}>
                <X size={20} />
              </button>
            </div>

            <form onSubmit={handleSaveForm} className="modal-body" style={{ display: 'flex', flexDirection: 'column', gap: '1.2rem' }}>
              <div>
                <label style={{ fontSize: '0.85rem', fontWeight: 700, display: 'block', marginBottom: '0.4rem' }}>
                  Bank Name *
                </label>
                <input
                  type="text"
                  required
                  style={{
                    width: '100%',
                    padding: '0.6rem 0.8rem',
                    borderRadius: '0.5rem',
                    border: '2px solid #000000',
                    background: 'var(--input-bg)',
                    color: 'var(--text-main)',
                    fontSize: '0.9rem'
                  }}
                  value={formData.bank_name}
                  onChange={(e) => setFormData({ ...formData, bank_name: e.target.value })}
                  placeholder="e.g. AXIS BANK, HDFC BANK"
                />
              </div>

              <div>
                <label style={{ fontSize: '0.85rem', fontWeight: 700, display: 'block', marginBottom: '0.4rem' }}>
                  Sample Statement PDF Filename
                </label>
                <input
                  type="text"
                  style={{
                    width: '100%',
                    padding: '0.6rem 0.8rem',
                    borderRadius: '0.5rem',
                    border: '2px solid #000000',
                    background: 'var(--input-bg)',
                    color: 'var(--text-main)',
                    fontSize: '0.9rem'
                  }}
                  value={formData.sample_file}
                  onChange={(e) => setFormData({ ...formData, sample_file: e.target.value })}
                  placeholder="e.g. AXIS.pdf"
                />
              </div>

              <div>
                <label style={{ fontSize: '0.85rem', fontWeight: 700, display: 'block', marginBottom: '0.4rem' }}>
                  Name Region Bounding Box Coordinates (Normalized 0.0 - 1.0)
                </label>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr 1fr', gap: '0.5rem' }}>
                  <div>
                    <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>x0</span>
                    <input
                      type="number"
                      step="0.001"
                      style={{
                        width: '100%',
                        padding: '0.4rem',
                        borderRadius: '0.375rem',
                        border: '1.5px solid #000000',
                        background: 'var(--input-bg)',
                        color: 'var(--text-main)',
                        fontSize: '0.85rem'
                      }}
                      value={formData.x0}
                      onChange={(e) => setFormData({ ...formData, x0: e.target.value })}
                    />
                  </div>
                  <div>
                    <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>y0</span>
                    <input
                      type="number"
                      step="0.001"
                      style={{
                        width: '100%',
                        padding: '0.4rem',
                        borderRadius: '0.375rem',
                        border: '1.5px solid #000000',
                        background: 'var(--input-bg)',
                        color: 'var(--text-main)',
                        fontSize: '0.85rem'
                      }}
                      value={formData.y0}
                      onChange={(e) => setFormData({ ...formData, y0: e.target.value })}
                    />
                  </div>
                  <div>
                    <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>x1</span>
                    <input
                      type="number"
                      step="0.001"
                      style={{
                        width: '100%',
                        padding: '0.4rem',
                        borderRadius: '0.375rem',
                        border: '1.5px solid #000000',
                        background: 'var(--input-bg)',
                        color: 'var(--text-main)',
                        fontSize: '0.85rem'
                      }}
                      value={formData.x1}
                      onChange={(e) => setFormData({ ...formData, x1: e.target.value })}
                    />
                  </div>
                  <div>
                    <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>y1</span>
                    <input
                      type="number"
                      step="0.001"
                      style={{
                        width: '100%',
                        padding: '0.4rem',
                        borderRadius: '0.375rem',
                        border: '1.5px solid #000000',
                        background: 'var(--input-bg)',
                        color: 'var(--text-main)',
                        fontSize: '0.85rem'
                      }}
                      value={formData.y1}
                      onChange={(e) => setFormData({ ...formData, y1: e.target.value })}
                    />
                  </div>
                </div>
              </div>

              <div>
                <label style={{ fontSize: '0.85rem', fontWeight: 700, display: 'block', marginBottom: '0.4rem' }}>
                  Configured Column Bounds (Format: Label:x0-x1, Label:x0-x1)
                </label>
                <input
                  type="text"
                  style={{
                    width: '100%',
                    padding: '0.6rem 0.8rem',
                    borderRadius: '0.5rem',
                    border: '2px solid #000000',
                    background: 'var(--input-bg)',
                    color: 'var(--text-main)',
                    fontSize: '0.85rem',
                    fontFamily: 'JetBrains Mono, monospace'
                  }}
                  value={formData.columnsText}
                  onChange={(e) => setFormData({ ...formData, columnsText: e.target.value })}
                  placeholder="Date:0.0-0.2, Description:0.2-0.6, Balance:0.6-1.0"
                />
              </div>

              <div style={{ marginTop: '0.5rem', marginBottom: '0.5rem' }}>
                <button
                  type="button"
                  style={{
                    width: '100%',
                    padding: '0.75rem',
                    borderRadius: '0.5rem',
                    border: '2px solid #000000',
                    background: 'var(--primary-light)',
                    color: 'var(--primary)',
                    fontWeight: 700,
                    fontSize: '0.9rem',
                    cursor: 'pointer',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    gap: '0.5rem'
                  }}
                  onClick={() => {
                    setShowModal(false);
                    if (onEditInCalibrator) {
                      onEditInCalibrator(formData.sample_file || `${formData.bank_name}.pdf`);
                    }
                  }}
                >
                  <Sliders size={18} />
                  <span>Open Interactive Calibrator for Visual Mapping</span>
                </button>
              </div>

              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '0.75rem', marginTop: '1rem' }}>
                <button
                  type="button"
                  style={{
                    padding: '0.6rem 1.2rem',
                    borderRadius: '0.5rem',
                    border: '2px solid #000000',
                    background: 'var(--input-bg)',
                    color: 'var(--text-main)',
                    fontWeight: 600,
                    cursor: 'pointer'
                  }}
                  onClick={() => setShowModal(false)}
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="header-btn-primary"
                  style={{
                    padding: '0.6rem 1.2rem',
                    borderRadius: '0.5rem',
                    fontWeight: 700,
                    cursor: 'pointer',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '0.35rem'
                  }}
                >
                  <Save size={16} />
                  <span>Save Registry</span>
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
