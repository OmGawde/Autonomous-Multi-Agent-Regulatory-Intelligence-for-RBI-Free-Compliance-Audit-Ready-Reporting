import React, { useEffect, useState, useRef, useMemo } from 'react';
import { ChevronLeft, ChevronRight, Save, Trash2, Eye, HelpCircle, Upload, ZoomIn, ZoomOut, RotateCcw, Search, X } from 'lucide-react';

import { BACKEND_URL } from '../apiConfig';

export default function InteractiveCalibrator({ initialPdf }) {
  const [statements, setStatements] = useState([]);
  const [selectedPdf, setSelectedPdf] = useState(initialPdf || '');
  const [uploadingPdf, setUploadingPdf] = useState(false);

  useEffect(() => {
    if (initialPdf) {
      setSelectedPdf(initialPdf);
    }
  }, [initialPdf]);

  const handleCalibratorPdfUpload = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    if (!file.name.toLowerCase().endsWith('.pdf') && file.type !== 'application/pdf') {
      alert('Please select a valid PDF file.');
      return;
    }

    setUploadingPdf(true);
    const formData = new FormData();
    formData.append('file', file);

    try {
      const res = await fetch(`${BACKEND_URL}/api/upload_calibrator_pdf`, {
        method: 'POST',
        body: formData,
      });

      if (res.ok) {
        const data = await res.json();
        const newFilename = data.filename;

        await fetchStatements();
        setSelectedPdf(newFilename);
      } else {
        alert('Failed to upload PDF for calibration.');
      }
    } catch (err) {
      console.error('Error uploading PDF for calibration:', err);
      alert('Network error while uploading PDF.');
    } finally {
      setUploadingPdf(false);
    }
  };

  const handleDeleteStatement = async (pdfName, e) => {
    e.stopPropagation();
    if (!window.confirm(`Are you sure you want to delete "${pdfName}" from Statement Archive?`)) return;

    try {
      const response = await fetch(`${BACKEND_URL}/api/delete_statement?pdf=${encodeURIComponent(pdfName)}`, {
        method: 'DELETE',
      });
      if (response.ok) {
        const remaining = statements.filter((item) => item !== pdfName);
        setStatements(remaining);
        if (selectedPdf === pdfName) {
          setSelectedPdf(remaining.length > 0 ? remaining[0] : '');
        }
      } else {
        alert('Failed to delete statement file.');
      }
    } catch (err) {
      console.error('Error deleting statement:', err);
      alert('Error deleting statement file.');
    }
  };

  const [pageCount, setPageCount] = useState(1);
  const [currentPage, setCurrentPage] = useState(0);
  const [imageSrc, setImageSrc] = useState('');
  const [loadingImage, setLoadingImage] = useState(false);
  const [zoom, setZoom] = useState(1.0);

  // Interaction State
  const [mode, setMode] = useState('name'); // 'name' (ROI Selection) or 'columns' (Column Calibration)
  const [isDrawing, setIsDrawing] = useState(false);
  const [startPos, setStartPos] = useState({ x: 0, y: 0 });
  const [selectionBox, setSelectionBox] = useState(null); // { x0, y0, x1, y1 } normalized 0 to 1
  const [rawText, setRawText] = useState('');
  const [extractingText, setExtractingText] = useState(false);
  const [pythonSnippet, setPythonSnippet] = useState('');

  // Column Calibration State
  const [columns, setColumns] = useState([]); // Array of { label, role, x0, x1 } normalized
  const [customColLabel, setCustomColLabel] = useState('date');

  // What the extractor needs beyond column positions. None of this was
  // collected before: the bank name was the upper-cased PDF filename stem, and
  // there was no date format or table region at all -- so nothing the
  // calibrator produced could actually drive a parse.
  const [calibratedBankName, setCalibratedBankName] = useState('');
  const [dateFormat, setDateFormat] = useState('%d-%m-%Y');
  const [tableRegion, setTableRegion] = useState(null); // {y0, y1} normalized
  const [ifscPrefix, setIfscPrefix] = useState('');
  const [detectMarkers, setDetectMarkers] = useState('');

  // Preview + verification feedback
  const [previewFidelity, setPreviewFidelity] = useState(null);
  const [previewColumns, setPreviewColumns] = useState([]);
  const [previewRowCount, setPreviewRowCount] = useState(0);
  const [previewError, setPreviewError] = useState('');
  const [previewTransactions, setPreviewTransactions] = useState([]);
  const [previewPage, setPreviewPage] = useState(1);
  const [previewPageSize, setPreviewPageSize] = useState(25);
  const [previewSearch, setPreviewSearch] = useState('');
  const [filterDate, setFilterDate] = useState(false);
  const [hasAutoPreset, setHasAutoPreset] = useState(false);
  const [showPreviewModal, setShowPreviewModal] = useState(false);
  const [loadingPreview, setLoadingPreview] = useState(false);

  // Toast notification state
  const [toast, setToast] = useState(null); // { message, type: 'success'|'error'|'info', id }
  const toastTimerRef = useRef(null);

  const showToast = (message, type = 'success', duration = 4000) => {
    const id = Date.now();
    if (toastTimerRef.current) clearTimeout(toastTimerRef.current);
    setToast({ message, type, id });
    toastTimerRef.current = setTimeout(() => setToast(null), duration);
  };

  useEffect(() => {
    const handleKeyDown = (e) => {
      if (e.key === 'Escape' && showPreviewModal) {
        setShowPreviewModal(false);
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [showPreviewModal]);

  const loadBankPreset = async (pdfName) => {
    if (!pdfName) return;
    setHasAutoPreset(false);
    try {
      const response = await fetch(`${BACKEND_URL}/api/bank-hashes`);
      if (!response.ok) return;
      const bankHashes = await response.json();
      if (!Array.isArray(bankHashes)) return;

      const cleanStem = pdfName.replace(/\.pdf$/i, '').trim().toLowerCase();
      const pdfLower = pdfName.trim().toLowerCase();

      let bankMatch = bankHashes.find((b) => {
        const bName = (b.bank_name || b.name || '').trim().toLowerCase();
        const hasMatchingImage = (b.images || []).some((img) => {
          const orig = (img.original_statement || '').trim().toLowerCase();
          return orig === pdfLower || orig === cleanStem || orig.replace(/\.pdf$/i, '') === cleanStem;
        });
        return hasMatchingImage || bName === cleanStem || pdfLower.includes(bName);
      });

      // If no direct filename match, query backend to match by image / header screenshot pHash
      if (!bankMatch) {
        try {
          const detectRes = await fetch(`${BACKEND_URL}/api/detect_bank?pdf=${encodeURIComponent(pdfName)}`);
          if (detectRes.ok) {
            const detectData = await detectRes.json();
            const detectedName = (detectData.detected_bank || '').trim().toLowerCase();
            if (detectedName && detectedName !== 'other') {
              bankMatch = bankHashes.find((b) => {
                const bName = (b.bank_name || b.name || '').trim().toLowerCase();
                return bName === detectedName || detectedName.includes(bName) || bName.includes(detectedName);
              });
            }
          }
        } catch (e) {
          console.error('Error auto-detecting bank via image/header phash:', e);
        }
      }

      if (bankMatch) {
        let presetFound = false;

        // Auto-load Name Coordinates if present
        if (bankMatch.name_coordinates && typeof bankMatch.name_coordinates.x0 === 'number') {
          const coords = bankMatch.name_coordinates;
          const box = {
            x0: coords.x0,
            y0: coords.y0,
            x1: coords.x1,
            y1: coords.y1,
          };
          setSelectionBox(box);
          presetFound = true;

          // Automatically extract text for auto-loaded box
          setExtractingText(true);
          try {
            const query = `pdf=${encodeURIComponent(pdfName)}&page=0&x0=${coords.x0}&y0=${coords.y0}&x1=${coords.x1}&y1=${coords.y1}`;
            const extRes = await fetch(`${BACKEND_URL}/api/extract?${query}`);
            if (extRes.ok) {
              const extData = await extRes.json();
              setRawText(extData.extracted_text || 'No text found');
              setPythonSnippet(extData.snippet || '');
            }
          } catch (e) {
            console.error('Error auto-extracting name text:', e);
          } finally {
            setExtractingText(false);
          }
        }

        // Auto-load Column Coordinates if present
        if (Array.isArray(bankMatch.columns) && bankMatch.columns.length > 0) {
          setColumns(bankMatch.columns);
          presetFound = true;

          // Automatically run preview transaction extraction
          try {
            await fetch(`${BACKEND_URL}/api/save_columns`, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ pdf: pdfName, columns: bankMatch.columns }),
            });
            const txQuery = `pdf=${encodeURIComponent(pdfName)}&filter_date=false`;
            const txRes = await fetch(`${BACKEND_URL}/api/extract_transactions?${txQuery}`);
            if (txRes.ok) {
              const txData = await txRes.json();
              if (txData.status === 'success') {
                setPreviewTransactions(txData.transactions || []);
                setPreviewPage(1);
                setPreviewSearch('');
              }
            }
          } catch (e) {
            console.error('Error auto-fetching preview transactions:', e);
          }
        }

        if (presetFound) {
          setHasAutoPreset(true);
        }
      }
    } catch (err) {
      console.error('Error auto-loading bank preset:', err);
    }
  };

  const filteredTransactions = useMemo(() => {
    if (!previewSearch.trim()) return previewTransactions;
    const q = previewSearch.toLowerCase();
    return previewTransactions.filter((row) =>
      Object.values(row).some((val) => String(val || '').toLowerCase().includes(q))
    );
  }, [previewTransactions, previewSearch]);

  const totalPreviewPages = useMemo(() => {
    return Math.max(1, Math.ceil(filteredTransactions.length / previewPageSize));
  }, [filteredTransactions.length, previewPageSize]);

  const currentPreviewRows = useMemo(() => {
    const start = (previewPage - 1) * previewPageSize;
    return filteredTransactions.slice(start, start + previewPageSize);
  }, [filteredTransactions, previewPage, previewPageSize]);

  const imageRef = useRef(null);
  const wrapperRef = useRef(null);
  const previewTableRef = useRef(null);

  const scrollToTable = () => {
    if (previewTableRef.current) {
      previewTableRef.current.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  };

  const [loadingStatements, setLoadingStatements] = useState(true);

  // Fetch statement list
  const fetchStatements = async () => {
    setLoadingStatements(true);
    try {
      const response = await fetch(`${BACKEND_URL}/api/statements`);
      if (response.ok) {
        const data = await response.json();
        setStatements(data);
        if (data.length > 0 && !initialPdf) setSelectedPdf(data[0]);
      }
    } catch (err) {
      console.error('Error fetching statements:', err);
    } finally {
      setLoadingStatements(false);
    }
  };

  useEffect(() => {
    fetchStatements();
  }, []);

  // Fetch page count & auto-load presets when PDF changes
  useEffect(() => {
    if (!selectedPdf) return;

    const fetchInfo = async () => {
      try {
        const response = await fetch(`${BACKEND_URL}/api/pdf_info?pdf=${encodeURIComponent(selectedPdf)}`);
        if (response.ok) {
          const data = await response.json();
          setPageCount(data.page_count || 1);
          setCurrentPage(0);
        }
      } catch (err) {
        console.error('Error fetching PDF info:', err);
      }
    };

    fetchInfo();
    setSelectionBox(null);
    setRawText('');
    setPythonSnippet('');
    setColumns([]);
    setPreviewTransactions([]);
    loadBankPreset(selectedPdf);
  }, [selectedPdf]);

  // Render PDF page when selectedPdf or page index changes
  useEffect(() => {
    if (!selectedPdf) return;

    const renderPage = async () => {
      setLoadingImage(true);
      setImageSrc(`${BACKEND_URL}/api/render?pdf=${encodeURIComponent(selectedPdf)}&page=${currentPage}`);
    };

    renderPage();
  }, [selectedPdf, currentPage]);

  const handleImageLoad = () => {
    setLoadingImage(false);
  };

  // Mouse Interactions for Drag Box Selection
  const handleMouseDown = (e) => {
    if (loadingImage || !imageRef.current) return;

    const rect = imageRef.current.getBoundingClientRect();
    const x = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
    const y = Math.max(0, Math.min(1, (e.clientY - rect.top) / rect.height));

    setIsDrawing(true);
    setRawText('');
    setExtractingText(false);
    setStartPos({ x, y });
    setSelectionBox({ x0: x, y0: y, x1: x, y1: y });
  };

  const handleMouseMove = (e) => {
    if (!isDrawing || !imageRef.current) return;

    const rect = imageRef.current.getBoundingClientRect();
    const currentX = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
    const currentY = Math.max(0, Math.min(1, (e.clientY - rect.top) / rect.height));

    setSelectionBox({
      x0: Math.min(startPos.x, currentX),
      y0: Math.min(startPos.y, currentY),
      x1: Math.max(startPos.x, currentX),
      y1: Math.max(startPos.y, currentY),
    });
  };

  const handleMouseUp = async () => {
    if (!isDrawing) return;
    setIsDrawing(false);

    if (!selectionBox) return;

    const width = selectionBox.x1 - selectionBox.x0;
    const height = selectionBox.y1 - selectionBox.y0;

    // Ignore small clicks
    if (width < 0.01 || height < 0.01) {
      setSelectionBox(null);
      setRawText('');
      return;
    }

    if (mode === 'name') {
      // Query text from coordinates
      setExtractingText(true);
      try {
        const query = `pdf=${encodeURIComponent(selectedPdf)}&page=${currentPage}&x0=${selectionBox.x0}&y0=${selectionBox.y0}&x1=${selectionBox.x1}&y1=${selectionBox.y1}`;
        const response = await fetch(`${BACKEND_URL}/api/extract?${query}`);
        if (response.ok) {
          const data = await response.json();
          setRawText(data.extracted_text || 'No text found');
          setPythonSnippet(data.snippet);
        }
      } catch (err) {
        console.error('Error extracting text:', err);
        setRawText('Error extracting text');
      } finally {
        setExtractingText(false);
      }
    } else if (mode === 'region') {
      // Mark the vertical extent of the transaction table. Explicit column
      // boundaries with no y-bound happily slice the customer's address block
      // into columns and admit it as table rows.
      setTableRegion({
        y0: parseFloat(selectionBox.y0.toFixed(4)),
        y1: parseFloat(selectionBox.y1.toFixed(4)),
      });
      setSelectionBox(null);
    } else {
      // mode is 'columns' - Add new column split range
      const label = customColLabel;
      const newCol = {
        label,
        role: label,
        x0: parseFloat(selectionBox.x0.toFixed(4)),
        x1: parseFloat(selectionBox.x1.toFixed(4)),
      };

      setColumns((prev) => {
        const filtered = prev.filter((col) => col.label !== label);
        return [...filtered, newCol].sort((a, b) => a.x0 - b.x0);
      });

      setSelectionBox(null);
    }
  };

  // Touch event handlers for mobile devices
  const handleTouchStart = (e) => {
    if (e.touches && e.touches[0]) {
      const touch = e.touches[0];
      handleMouseDown({ clientX: touch.clientX, clientY: touch.clientY });
    }
  };

  const handleTouchMove = (e) => {
    if (e.touches && e.touches[0]) {
      const touch = e.touches[0];
      handleMouseMove({ clientX: touch.clientX, clientY: touch.clientY });
    }
  };

  const handleTouchEnd = () => {
    handleMouseUp();
  };

  // Action: Save Name Coordinates
  const handleSaveName = async () => {
    if (!selectionBox) {
      alert('Draw a selection box over the Account Holder Name first.');
      return;
    }

    try {
      const response = await fetch(`${BACKEND_URL}/api/save`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          pdf: selectedPdf,
          coordinates: {
            x0: selectionBox.x0,
            y0: selectionBox.y0,
            x1: selectionBox.x1,
            y1: selectionBox.y1,
          },
        }),
      });

      if (response.ok) {
        const data = await response.json();
        if (data.updated) {
          showToast('Name extraction coordinates saved successfully to statement registry.', 'success');
        } else {
          showToast('Could not find matching bank hash in database. Run upload first.', 'error');
        }
      }
    } catch (err) {
      console.error('Error saving name:', err);
    }
  };

  // Action: Delete configured column
  const handleDeleteColumn = (label) => {
    setColumns((prev) => prev.filter((col) => col.label !== label));
  };

  // The calibration currently on screen, in the shape the backend expects.
  const buildCalibrationPayload = () => ({
    pdf: selectedPdf,
    bank_name: calibratedBankName.trim(),
    columns: columns.map((c) => ({
      label: c.label,
      role: (c.role || c.label || '').toLowerCase(),
      x0: c.x0,
      x1: c.x1,
    })),
    date_format: dateFormat || null,
    table_region: tableRegion,
    ifsc_prefix: ifscPrefix.trim() || null,
    detect_markers: detectMarkers.trim() ? detectMarkers.split(',').map((m) => m.trim()) : null,
  });

  // Action: parse the statement with the calibration being edited, and report
  // whether the result agrees with the figures printed on the statement. This
  // is the feedback loop -- previously the preview ran generic auto-detection
  // and ignored the drawn columns entirely, so it could never show the effect
  // of a change.
  const handlePreviewTransactions = async () => {
    if (columns.length === 0) {
      alert('Mark at least one column first.');
      return;
    }

    setShowPreviewModal(true);
    setLoadingPreview(true);
    setPreviewTransactions([]);
    setPreviewFidelity(null);
    setPreviewError('');
    setPreviewPage(1);
    setPreviewSearch('');

    try {
      const response = await fetch(`${BACKEND_URL}/api/calibration/preview`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(buildCalibrationPayload()),
      });
      const data = await response.json();

      if (response.ok) {
        setPreviewTransactions(data.rows || []);
        setPreviewColumns(data.columns || []);
        setPreviewRowCount(data.row_count || 0);
        setPreviewFidelity(data.fidelity || null);
      } else {
        const detail = data.detail;
        setPreviewError(
          typeof detail === 'object' && detail ? detail.message : detail || 'Preview failed.'
        );
      }
    } catch (err) {
      console.error('Error loading transaction preview:', err);
      setPreviewError('Could not reach the backend.');
    } finally {
      setLoadingPreview(false);
    }
  };

  // Action: persist the calibration as a real bank template the extractor uses.
  const handleSaveColumns = async () => {
    if (columns.length === 0) {
      alert('Mark the columns before saving.');
      return;
    }
    if (!calibratedBankName.trim()) {
      alert('Give this bank a name. It is how the template is looked up on a future upload.');
      return;
    }

    try {
      const response = await fetch(`${BACKEND_URL}/banks/save-template`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(buildCalibrationPayload()),
      });
      const data = await response.json();

      if (response.ok) {
        showToast(
          `Saved '${data.bank_name}' — ${data.roles.length} columns. Statements from this bank will now parse.`,
          'success'
        );
      } else {
        const detail = data.detail;
        showToast(
          typeof detail === 'object' && detail ? detail.message : detail || 'Could not save template.',
          'error'
        );
      }
    } catch (err) {
      console.error('Error saving columns:', err);
      showToast('Could not reach the backend.', 'error');
    }
  };

  // Render selection box overlay
  const renderSelectionBoxStyle = () => {
    if (!selectionBox || !imageRef.current || loadingImage) return { display: 'none' };

    return {
      left: `${selectionBox.x0 * 100}%`,
      top: `${selectionBox.y0 * 100}%`,
      width: `${(selectionBox.x1 - selectionBox.x0) * 100}%`,
      height: `${(selectionBox.y1 - selectionBox.y0) * 100}%`,
      display: 'block',
    };
  };

  return (
    <div className="calibrator-layout">
      {/* Sidebar - Statement List */}
      <div className="calibrator-sidebar">
        <div style={{ marginBottom: '1.5rem', paddingBottom: '1rem', borderBottom: '1px solid var(--border-color)' }}>
          <h3 style={{ fontSize: '1rem', marginBottom: '0.75rem' }}>Upload Statement</h3>
          <label
            htmlFor="calibrator-pdf-input"
            style={{
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              justifyContent: 'center',
              padding: '1.25rem 1rem',
              border: '2px dashed var(--primary)',
              borderRadius: '0.75rem',
              background: 'rgba(59, 130, 246, 0.05)',
              cursor: 'pointer',
              textAlign: 'center',
              transition: 'all 0.2s ease'
            }}
          >
            <Upload size={22} style={{ color: 'var(--primary)', marginBottom: '0.35rem' }} />
            <span style={{ fontSize: '0.85rem', fontWeight: 600, color: 'var(--primary)' }}>
              {uploadingPdf ? 'Uploading...' : 'Upload PDF File'}
            </span>
            <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)', marginTop: '0.2rem' }}>
              Map name & column bounds
            </span>
            <input
              id="calibrator-pdf-input"
              type="file"
              accept=".pdf"
              style={{ display: 'none' }}
              onChange={handleCalibratorPdfUpload}
              disabled={uploadingPdf}
            />
          </label>
        </div>

        <h3 style={{ fontSize: '1rem', marginBottom: '0.75rem' }}>Statement Archive</h3>
        <div className="calibrator-statement-list">
          {loadingStatements ? (
            <p style={{ color: 'var(--text-muted)', fontSize: '0.85rem' }}>
              Loading statement archive...
            </p>
          ) : statements.length === 0 ? (
            <p style={{ color: 'var(--text-muted)', fontSize: '0.85rem' }}>
              No PDF statements found. Go to 'Upload Statement' to add files.
            </p>
          ) : (
            statements.map((s, idx) => (
              <div
                key={idx}
                className={`calibrator-statement-item ${selectedPdf === s ? 'active' : ''}`}
                onClick={() => setSelectedPdf(s)}
                title={s}
                style={{ justifyContent: 'space-between' }}
              >
                <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flex: 1, minWidth: 0 }}>
                  {s}
                </span>
                <button
                  className="stmt-delete-btn"
                  onClick={(e) => handleDeleteStatement(s, e)}
                  title={`Delete ${s}`}
                >
                  <Trash2 size={13} />
                </button>
              </div>
            ))
          )}
        </div>
      </div>

      {/* Main Column - PDF Viewer Canvas */}
      <div className="calibrator-canvas-area">
        {selectedPdf ? (
          <>
            {/* Canvas Toolbar */}
            <div className="canvas-toolbar">
              <div className="page-indicators">
                <button
                  className="page-indicator-btn"
                  disabled={currentPage === 0}
                  onClick={() => setCurrentPage((p) => p - 1)}
                  title="Previous Page"
                >
                  <ChevronLeft size={16} />
                </button>
                <span style={{ fontSize: '0.85rem', fontWeight: 600 }}>
                  Page {currentPage + 1} of {pageCount}
                </span>
                <button
                  className="page-indicator-btn"
                  disabled={currentPage >= pageCount - 1}
                  onClick={() => setCurrentPage((p) => p + 1)}
                  title="Next Page"
                >
                  <ChevronRight size={16} />
                </button>
              </div>

              {/* Zoom Controls */}
              <div className="zoom-controls">
                <button
                  className="page-indicator-btn"
                  disabled={zoom <= 0.5}
                  onClick={() => setZoom((z) => Math.max(0.5, Math.round((z - 0.25) * 100) / 100))}
                  title="Zoom Out"
                >
                  <ZoomOut size={16} />
                </button>
                <span style={{ fontSize: '0.85rem', fontWeight: 600, minWidth: '3.5rem', textAlign: 'center' }}>
                  {Math.round(zoom * 100)}%
                </span>
                <button
                  className="page-indicator-btn"
                  disabled={zoom >= 2.5}
                  onClick={() => setZoom((z) => Math.min(2.5, Math.round((z + 0.25) * 100) / 100))}
                  title="Zoom In"
                >
                  <ZoomIn size={16} />
                </button>
                <button
                  className="page-indicator-btn"
                  onClick={() => setZoom(1.0)}
                  title="Reset Zoom (100%)"
                >
                  <RotateCcw size={14} />
                </button>
              </div>
            </div>

            {/* Canvas Wrapper */}
            <div
              className="canvas-image-wrapper"
              ref={wrapperRef}
              style={{
                width: `${Math.round(zoom * 800)}px`,
                maxWidth: zoom > 1 ? 'none' : '100%',
              }}
              onMouseDown={handleMouseDown}
              onMouseMove={handleMouseMove}
              onMouseUp={handleMouseUp}
              onTouchStart={handleTouchStart}
              onTouchMove={handleTouchMove}
              onTouchEnd={handleTouchEnd}
            >
              {loadingImage && (
                <div style={{ position: 'absolute', top: '50%', left: '50%', transform: 'translate(-50%, -50%)', background: 'var(--bg-surface)', border: '2px solid #000000', padding: '0.75rem 1.5rem', borderRadius: '0.5rem', zIndex: 20, fontSize: '0.85rem', fontWeight: 600, color: 'var(--primary)', boxShadow: 'var(--card-shadow)' }}>
                  Rendering PDF page {currentPage + 1}...
                </div>
              )}
              {imageSrc && (
                <img
                  src={imageSrc}
                  alt="PDF page"
                  className="canvas-pdf-image"
                  ref={imageRef}
                  onLoad={handleImageLoad}
                  onError={() => setLoadingImage(false)}
                  style={{ opacity: loadingImage ? 0.3 : 1, transition: 'opacity 0.2s ease' }}
                />
              )}

              {/* Selection Box Overlay */}
              <div className="canvas-selection-box" style={renderSelectionBoxStyle()}>
                {selectionBox && (selectionBox.x1 - selectionBox.x0 > 0.01) && (
                  <div className="selection-box-badge">
                    {((selectionBox.x1 - selectionBox.x0) * 100).toFixed(1)}% × {((selectionBox.y1 - selectionBox.y0) * 100).toFixed(1)}%
                  </div>
                )}

                {mode === 'name' && !isDrawing && (
                  <div className="selection-box-text-container">
                    {extractingText ? (
                      <span className="selection-box-extracting">Extracting text...</span>
                    ) : rawText ? (
                      <span className="selection-box-extracted-text" title={rawText}>
                        🔤 {rawText}
                      </span>
                    ) : null}
                  </div>
                )}
              </div>

              {/* Vertical Column Overlays */}
              {mode === 'columns' &&
                columns.map((col, idx) => (
                  <div
                    key={idx}
                    className="col-overlay"
                    style={{
                      left: `${col.x0 * 100}%`,
                      width: `${(col.x1 - col.x0) * 100}%`,
                    }}
                  >
                    <div className="col-overlay-label">{col.label}</div>
                  </div>
                ))}
            </div>

          </>
        ) : (
          <div style={{ textAlign: 'center', padding: '4rem', color: 'var(--text-muted)' }}>
            <HelpCircle size={48} style={{ margin: '0 auto 1rem auto', opacity: 0.3 }} />
            Please select a PDF document from the archive list.
          </div>
        )}
      </div>

      {/* Right Column - Calibrator Toolset */}
      <div className="calibrator-panel">
        <div className="mode-tabs">
          <button
            className={`mode-btn ${mode === 'name' ? 'active' : ''}`}
            onClick={() => setMode('name')}
          >
            Name Extractor
          </button>
          <button
            className={`mode-btn ${mode === 'columns' ? 'active' : ''}`}
            onClick={() => setMode('columns')}
          >
            Column Mapper
          </button>
          <button
            className={`mode-btn ${mode === 'region' ? 'active' : ''}`}
            onClick={() => setMode('region')}
          >
            Table Area
          </button>
        </div>

        {mode === 'region' && (
          <div className="calibrator-card">
            <h4>Transaction Table Area</h4>
            <p style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
              Drag a box over the transaction rows only — not the header block or the
              address. Column boundaries alone will otherwise slice the address into
              columns and read it as transactions.
            </p>
            {tableRegion ? (
              <div style={{ fontSize: '0.8rem', marginTop: '0.6rem' }}>
                Marked: top {(tableRegion.y0 * 100).toFixed(1)}% → bottom{' '}
                {(tableRegion.y1 * 100).toFixed(1)}% of the page
                <button
                  className="btn-secondary"
                  style={{ marginLeft: '0.6rem', padding: '0.2rem 0.55rem', fontSize: '0.72rem' }}
                  onClick={() => setTableRegion(null)}
                >
                  Clear
                </button>
              </div>
            ) : (
              <p style={{ fontSize: '0.78rem', marginTop: '0.5rem', color: 'var(--text-muted)' }}>
                Not set — the whole page will be searched.
              </p>
            )}
          </div>
        )}

        {mode === 'name' ? (
          <>
            <div className="calibrator-card">
              <h4>Account Holder Area</h4>
              <p style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                Drag a bounding box over the account holder name inside the PDF layout to configure automated matching.
              </p>

              <div className="calibrator-coord-grid">
                <div className="calibrator-coord-box">
                  <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>Top Left</div>
                  <div className="calibrator-coord-val">
                    X: {selectionBox ? selectionBox.x0.toFixed(3) : '0.000'}
                  </div>
                  <div className="calibrator-coord-val">
                    Y: {selectionBox ? selectionBox.y0.toFixed(3) : '0.000'}
                  </div>
                </div>
                <div className="calibrator-coord-box">
                  <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>Bottom Right</div>
                  <div className="calibrator-coord-val">
                    X: {selectionBox ? selectionBox.x1.toFixed(3) : '0.000'}
                  </div>
                  <div className="calibrator-coord-val">
                    Y: {selectionBox ? selectionBox.y1.toFixed(3) : '0.000'}
                  </div>
                </div>
              </div>

              <div style={{ marginTop: '0.75rem', marginBottom: '0.75rem' }}>
                <div style={{ fontSize: '0.8rem', fontWeight: 600, marginBottom: '0.35rem', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                  <span>Extracted Text Preview:</span>
                  {rawText && <span style={{ fontSize: '0.7rem', color: 'var(--primary)', fontWeight: 700 }}>✓ Extracted</span>}
                </div>
                <div className="calibrator-extracted-box" style={{ minHeight: '48px', display: 'flex', alignItems: 'center' }}>
                  {extractingText ? (
                    <span style={{ color: '#f59e0b', fontStyle: 'italic', fontSize: '0.8rem' }}>Extracting text from ROI...</span>
                  ) : rawText ? (
                    <strong style={{ color: 'var(--text-main)', fontSize: '0.85rem', wordBreak: 'break-word' }}>{rawText}</strong>
                  ) : (
                    <span style={{ color: 'var(--text-muted)', fontSize: '0.75rem', fontStyle: 'italic' }}>
                      Draw a bounding box over text on the PDF to extract.
                    </span>
                  )}
                </div>
              </div>

              <button className="submit-btn" style={{ height: '38px', padding: 0 }} onClick={handleSaveName}>
                <Save size={16} style={{ display: 'inline', marginRight: '0.35rem', verticalAlign: 'middle' }} />
                Save Coordinates Rule
              </button>
            </div>

            {pythonSnippet && (
              <div className="calibrator-card">
                <h4>Generated Code Snippet</h4>
                <div className="calibrator-code-snippet">{pythonSnippet}</div>
              </div>
            )}
          </>
        ) : (
          <>
            {/* Everything the extractor needs beyond column positions. None of
                this used to be collected -- the bank name was the upper-cased
                PDF filename, and there was no date format at all. */}
            <div className="calibrator-card">
              <h4>Bank Details</h4>
              <div className="form-group" style={{ marginBottom: '0.6rem' }}>
                <label style={{ fontSize: '0.75rem' }}>Bank Name *</label>
                <input
                  className="form-control"
                  style={{ height: '38px', padding: '0 0.75rem' }}
                  value={calibratedBankName}
                  onChange={(e) => setCalibratedBankName(e.target.value)}
                  placeholder="e.g. Canara Bank"
                />
                <p style={{ fontSize: '0.7rem', color: 'var(--text-muted)', margin: '0.3rem 0 0 0' }}>
                  How this template is looked up on a future upload.
                </p>
              </div>
              <div className="form-group" style={{ marginBottom: '0.6rem' }}>
                <label style={{ fontSize: '0.75rem' }}>Date Format *</label>
                <select
                  className="form-control"
                  style={{ height: '38px', padding: '0 0.75rem' }}
                  value={dateFormat}
                  onChange={(e) => setDateFormat(e.target.value)}
                >
                  <option value="%d-%m-%Y">31-03-2026 (DD-MM-YYYY)</option>
                  <option value="%d/%m/%Y">31/03/2026 (DD/MM/YYYY)</option>
                  <option value="%d.%m.%Y">31.03.2026 (DD.MM.YYYY)</option>
                  <option value="%Y-%m-%d">2026-03-31 (YYYY-MM-DD)</option>
                  <option value="%d-%b-%Y">31-Mar-2026 (DD-Mon-YYYY)</option>
                  <option value="%d %b %Y">31 Mar 2026</option>
                </select>
              </div>
              <div className="form-group" style={{ marginBottom: '0.6rem' }}>
                <label style={{ fontSize: '0.75rem' }}>IFSC Prefix (first 4 letters)</label>
                <input
                  className="form-control"
                  style={{ height: '38px', padding: '0 0.75rem' }}
                  value={ifscPrefix}
                  onChange={(e) => setIfscPrefix(e.target.value.toUpperCase())}
                  maxLength={4}
                  placeholder="e.g. CNRB"
                />
              </div>
              <div className="form-group">
                <label style={{ fontSize: '0.75rem' }}>Header Text Markers (comma separated)</label>
                <input
                  className="form-control"
                  style={{ height: '38px', padding: '0 0.75rem' }}
                  value={detectMarkers}
                  onChange={(e) => setDetectMarkers(e.target.value)}
                  placeholder="e.g. canara bank, www.canarabank.com"
                />
                <p style={{ fontSize: '0.7rem', color: 'var(--text-muted)', margin: '0.3rem 0 0 0' }}>
                  Used to recognise this bank automatically. Without an IFSC prefix or a
                  marker, the name has to be typed on every upload.
                </p>
              </div>
            </div>

            <div className="calibrator-card">
              <h4>Setup Table Boundaries</h4>
              <p style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                Pick what a column holds, then drag a box over its left and right edges.
                A Date column, a Balance column and at least one of Debit/Credit are required.
              </p>

              <div className="form-group" style={{ marginBottom: '0.5rem' }}>
                <label style={{ fontSize: '0.75rem' }}>Column Field Tag</label>
                <select
                  className="form-control"
                  style={{ height: '38px', padding: '0 0.75rem' }}
                  value={customColLabel}
                  onChange={(e) => setCustomColLabel(e.target.value)}
                >
                  <option value="date">Date</option>
                  <option value="time">Time / Timestamp (Optional)</option>
                  <option value="description">Description / Narration</option>
                  <option value="debit">Debit (Withdrawal)</option>
                  <option value="credit">Credit (Deposit)</option>
                  <option value="balance">Balance</option>
                  <option value="cheque">Cheque / Reference No.</option>
                  <option value="value_date">Value Date</option>
                  <option value="serial">Serial No.</option>
                  <option value="ignore">Ignore this column</option>
                </select>
              </div>
            </div>

            <div className="calibrator-card">
              <h4>Configured Columns ({columns.length})</h4>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem', maxHeight: '180px', overflowY: 'auto', overflowX: 'hidden' }}>
                {columns.length === 0 ? (
                  <p style={{ color: 'var(--text-muted)', fontSize: '0.75rem', textAlign: 'center', padding: '1rem' }}>
                    No column zones drawn yet.
                  </p>
                ) : (
                  columns.map((col, idx) => (
                    <div
                      key={idx}
                      style={{
                        display: 'flex',
                        justifyContent: 'space-between',
                        alignItems: 'center',
                        padding: '0.5rem',
                        paddingLeft: '2px',
                        background: 'rgba(255,255,255,0.01)',
                        border: '1px solid var(--border-color)',
                        borderRadius: '0.5rem',
                        fontSize: '0.8rem',
                        whiteSpace: 'nowrap',
                        overflow: 'hidden',
                        gap: '0.5rem',
                      }}
                    >
                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.35rem', overflow: 'hidden', minWidth: 0 }}>
                        <span className="calibrator-column-badge" style={{ flexShrink: 0 }}>{col.label}</span>
                        <span style={{ fontFamily: 'monospace', color: 'var(--text-muted)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', fontSize: '0.72rem' }}>
                          [{col.x0} - {col.x1}]
                        </span>
                      </div>
                      <button
                        style={{ background: 'transparent', border: 'none', color: '#ef4444', cursor: 'pointer' }}
                        onClick={() => handleDeleteColumn(col.label)}
                      >
                        <Trash2 size={14} />
                      </button>
                    </div>
                  ))
                )}
              </div>

              {columns.length > 0 && (
                <>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', margin: '0.5rem 0' }}>
                    <input
                      type="checkbox"
                      id="filter_date_box"
                      checked={filterDate}
                      onChange={(e) => setFilterDate(e.target.checked)}
                    />
                    <label htmlFor="filter_date_box" style={{ fontSize: '0.75rem', cursor: 'pointer', color: 'var(--text-muted)' }}>
                      Filter Date Rows (validate format)
                    </label>
                  </div>

                  <div style={{ display: 'flex', gap: '0.5rem' }}>
                    <button
                      className="submit-btn"
                      style={{ flex: 1, background: 'rgba(255,255,255,0.05)', color: 'var(--text-main)', border: '1px solid var(--border-color)', boxShadow: 'none', height: '28px', padding: '1rem 0.5rem', fontSize: '0.75rem', alignItems: 'center', justifyContent: 'center', display: 'flex' }}
                      onClick={handlePreviewTransactions}
                    >
                      <Eye size={12} style={{ display: 'inline', marginRight: '0.25rem', verticalAlign: 'middle' }} />
                      Preview
                    </button>
                    <button
                      className="submit-btn"
                      style={{ flex: 1, height: '28px', padding: '1rem 0.5rem', fontSize: '0.75rem', alignItems: 'center', justifyContent: 'center', display: 'flex' }}
                      onClick={handleSaveColumns}
                    >
                      <Save size={12} style={{ display: 'inline', marginRight: '0.25rem', verticalAlign: 'middle' }} />
                      Save Layout
                    </button>
                  </div>
                </>
              )}
            </div>
          </>
        )}
      </div>

      {/* Transaction Preview Dialog Modal */}
      {showPreviewModal && (
        <div
          className="preview-modal-overlay"
          onClick={() => setShowPreviewModal(false)}
        >
          <div
            className="preview-modal-dialog"
            onClick={(e) => e.stopPropagation()}
          >
            {/* Modal Header */}
            <div className="preview-modal-header">
              <div className="preview-modal-title-group">
                <h3 className="preview-modal-title">Live Parsed Transaction Preview</h3>
                <span className="preview-row-count-badge">
                  {filteredTransactions.length.toLocaleString()} rows
                </span>
              </div>

              <div className="preview-modal-actions">
                {/* Search Input */}
                <div className="preview-search-wrapper">
                  <Search size={14} className="preview-search-icon" />
                  <input
                    type="text"
                    className="preview-search-input"
                    placeholder="Search transactions..."
                    value={previewSearch}
                    onChange={(e) => {
                      setPreviewSearch(e.target.value);
                      setPreviewPage(1);
                    }}
                  />
                </div>

                {/* Page Size Selector */}
                <select
                  className="preview-page-size-select"
                  value={previewPageSize}
                  onChange={(e) => {
                    setPreviewPageSize(Number(e.target.value));
                    setPreviewPage(1);
                  }}
                >
                  <option value={10}>10 / page</option>
                  <option value={25}>25 / page</option>
                  <option value={50}>50 / page</option>
                  <option value={100}>100 / page</option>
                  <option value={500}>500 / page</option>
                </select>

                {/* Close Button */}
                <button
                  className="preview-modal-close-btn"
                  onClick={() => setShowPreviewModal(false)}
                  title="Close Preview Modal (Esc)"
                >
                  <X size={18} />
                </button>
              </div>
            </div>

            {/* Modal Body Table */}
            <div className="preview-modal-body">
              {loadingPreview ? (
                <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', padding: '6rem 2rem', gap: '1.25rem', color: 'var(--text-muted)' }}>
                  <div style={{ width: '42px', height: '42px', border: '3.5px solid var(--border-color)', borderTopColor: 'var(--primary)', borderRadius: '50%', animation: 'spin 0.8s linear infinite' }} />
                  <div style={{ textAlign: 'center' }}>
                    <span style={{ fontSize: '1rem', fontWeight: 700, color: 'var(--text-main)', display: 'block', marginBottom: '0.35rem' }}>
                      Extracting & Parsing Transactions...
                    </span>
                    <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>
                      Analyzing column boundaries for {selectedPdf}
                    </span>
                  </div>
                </div>
              ) : (
                <>
                {/* The verification verdict. This is what makes calibration a
                    closed loop -- rather than eyeballing 300 rows, the operator
                    sees whether the parse agrees with the statement's own
                    printed totals. */}
                {previewError && (
                  <div style={{ margin: '0 0 1rem 0', padding: '0.8rem 1rem', border: '1.5px solid #ef4444',
                                borderRadius: '8px', background: 'rgba(239,68,68,0.08)', fontSize: '0.85rem' }}>
                    {previewError}
                  </div>
                )}
                {previewFidelity && (
                  <div
                    style={{
                      margin: '0 0 1rem 0', padding: '0.85rem 1rem', borderRadius: '8px',
                      border: `1.5px solid ${previewFidelity.status === 'VERIFIED' ? '#22c55e'
                        : previewFidelity.status === 'FAILED' ? '#ef4444' : '#f59e0b'}`,
                      background: previewFidelity.status === 'VERIFIED' ? 'rgba(34,197,94,0.08)'
                        : previewFidelity.status === 'FAILED' ? 'rgba(239,68,68,0.08)' : 'rgba(245,158,11,0.08)',
                    }}
                  >
                    <strong style={{ fontSize: '0.9rem' }}>
                      {previewFidelity.status === 'VERIFIED' && `Matches the statement — ${previewRowCount} rows parsed`}
                      {previewFidelity.status === 'FAILED' && `Does not match the statement — ${previewRowCount} rows parsed`}
                      {previewFidelity.status === 'UNVERIFIED' && `${previewRowCount} rows parsed — nothing on the statement to check against`}
                    </strong>
                    {previewFidelity.reason && (
                      <p style={{ fontSize: '0.78rem', color: 'var(--text-muted)', margin: '0.35rem 0 0 0' }}>
                        {previewFidelity.reason}
                      </p>
                    )}
                    {Array.isArray(previewFidelity.checks) && previewFidelity.checks.length > 0 && (
                      <ul style={{ margin: '0.5rem 0 0 0', paddingLeft: '1.1rem', fontSize: '0.78rem' }}>
                        {previewFidelity.checks.map((c, i) => (
                          <li key={i} style={{ color: c.passed ? '#16a34a' : '#ef4444' }} title={c.detail || ''}>
                            {c.check}: statement says {String(c.expected)}
                            {c.passed ? ' — matches' : `, we read ${String(c.actual)}`}
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                )}
                <table className="preview-table">
                  <thead>
                    <tr>
                      <th style={{ width: '50px', textAlign: 'center' }}>#</th>
                      {previewColumns.map((col, idx) => (
                        <th key={idx}>{col}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {currentPreviewRows.length > 0 ? (
                      currentPreviewRows.map((row, idx) => {
                        const rowIndex = (previewPage - 1) * previewPageSize + idx + 1;
                        return (
                          <tr key={idx}>
                            <td className="preview-row-index">{rowIndex}</td>
                            {previewColumns.map((col, cIdx) => {
                              // The backend returns lower-case keys ('date',
                              // 'debit'). The old code indexed with the UI's
                              // display labels ('Date', 'Debit'), so every
                              // single cell resolved to undefined and rendered
                              // as '-' -- the preview could never show anything.
                              const val = row[col];
                              const isAmount = ['debit', 'credit', 'balance'].includes(col);
                              return (
                                <td key={cIdx} className={isAmount ? 'numeric-cell' : ''}>
                                  {val === null || val === undefined || val === '' ? '-' : String(val)}
                                </td>
                              );
                            })}
                          </tr>
                        );
                      })
                    ) : (
                      <tr>
                        <td
                          colSpan={previewColumns.length + 1}
                          style={{ textAlign: 'center', padding: '3rem', color: 'var(--text-muted)' }}
                        >
                          {previewSearch
                            ? `No transactions match "${previewSearch}"`
                            : 'No rows parsed with this calibration. Check the column boundaries and the table area.'}
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
                </>
              )}
            </div>

            {/* Modal Footer */}
            <div className="preview-modal-footer">
              <span className="preview-pagination-info">
                Showing {filteredTransactions.length > 0 ? ((previewPage - 1) * previewPageSize + 1).toLocaleString() : 0} to{' '}
                {Math.min(previewPage * previewPageSize, filteredTransactions.length).toLocaleString()} of{' '}
                {filteredTransactions.length.toLocaleString()} transactions
              </span>

              <div className="preview-pagination-buttons">
                <button
                  className="page-indicator-btn"
                  disabled={previewPage <= 1}
                  onClick={() => setPreviewPage(1)}
                  title="First Page"
                >
                  «
                </button>
                <button
                  className="page-indicator-btn"
                  disabled={previewPage <= 1}
                  onClick={() => setPreviewPage((p) => Math.max(1, p - 1))}
                  title="Previous Page"
                >
                  <ChevronLeft size={16} />
                </button>
                <span className="preview-page-text">
                  Page {previewPage} of {totalPreviewPages}
                </span>
                <button
                  className="page-indicator-btn"
                  disabled={previewPage >= totalPreviewPages}
                  onClick={() => setPreviewPage((p) => Math.min(totalPreviewPages, p + 1))}
                  title="Next Page"
                >
                  <ChevronRight size={16} />
                </button>
                <button
                  className="page-indicator-btn"
                  disabled={previewPage >= totalPreviewPages}
                  onClick={() => setPreviewPage(totalPreviewPages)}
                  title="Last Page"
                >
                  »
                </button>
                <button
                  className="submit-btn"
                  style={{ marginLeft: '1rem', height: '32px', padding: '0 0.85rem', fontSize: '0.8rem' }}
                  onClick={() => setShowPreviewModal(false)}
                >
                  Close
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
      {/* Toast Notification Dialog */}
      {toast && (
        <div
          key={toast.id}
          className={`calibrator-toast calibrator-toast--${toast.type}`}
          role="alert"
        >
          <span className="calibrator-toast__message">{toast.message}</span>
          <button
            className="calibrator-toast__close"
            onClick={() => { if (toastTimerRef.current) clearTimeout(toastTimerRef.current); setToast(null); }}
            aria-label="Dismiss"
          >
            ×
          </button>
        </div>
      )}
    </div>
  );
}
