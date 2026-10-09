import React, { useState, useRef } from 'react';
import { Upload, AlertCircle, CheckCircle, Loader } from 'lucide-react';

import { BACKEND_URL } from '../apiConfig';

export default function UploadForm({ onUploadComplete }) {
  const [files, setFiles] = useState([]);
  const [bankName, setBankName] = useState('Auto-Detect');
  const [customBankName, setCustomBankName] = useState('');
  const [pdfType, setPdfType] = useState('digital');
  
  const [dragActive, setDragActive] = useState(false);
  const [uploadState, setUploadState] = useState('idle'); // idle, uploading, processing, success, error
  const [errorMessage, setErrorMessage] = useState('');
  const [currentAppId, setCurrentAppId] = useState('');
  
  const [pipelineProgress, setPipelineProgress] = useState(10);
  const [pipelineMessage, setPipelineMessage] = useState('Initializing statement processing pipeline...');
  const [backendStatus, setBackendStatus] = useState('pending'); // pending, detecting, extracting, scoring, success, failed
  const [detectedBank, setDetectedBank] = useState('');
  const [detectedApplicant, setDetectedApplicant] = useState('');

  // Password-protected statements. The backend rejects the upload with 422
  // before creating an application, so the user can supply the password and
  // resubmit the same file. It is sent per-request and never stored.
  const [pdfPassword, setPdfPassword] = useState('');
  const [needsPassword, setNeedsPassword] = useState(false);
  const [passwordHint, setPasswordHint] = useState('');

  const fileInputRef = useRef(null);

  const handleDrag = (e) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === 'dragenter' || e.type === 'dragover') {
      setDragActive(true);
    } else if (e.type === 'dragleave') {
      setDragActive(false);
    }
  };

  const handleDrop = (e) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);
    
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      const droppedFiles = Array.from(e.dataTransfer.files).filter(
        f => f.type === 'application/pdf' || f.name.toLowerCase().endsWith('.pdf')
      );
      if (droppedFiles.length > 0) {
        setFiles(prev => [...prev, ...droppedFiles]);
      } else {
        alert('Only PDF files are supported.');
      }
    }
  };

  const handleFileChange = (e) => {
    if (e.target.files && e.target.files.length > 0) {
      const selected = Array.from(e.target.files).filter(
        f => f.type === 'application/pdf' || f.name.toLowerCase().endsWith('.pdf')
      );
      setFiles(prev => [...prev, ...selected]);
    }
  };

  const removeFile = (indexToRemove, e) => {
    if (e) {
      e.stopPropagation();
    }
    setFiles(prev => prev.filter((_, idx) => idx !== indexToRemove));
  };

  // Poll Application Status
  const pollStatus = (appId) => {
    const interval = setInterval(async () => {
      try {
        const response = await fetch(`${BACKEND_URL}/status/${appId}`);
        if (response.ok) {
          const data = await response.json();
          if (data.status) setBackendStatus(data.status);
          if (data.progress) setPipelineProgress(data.progress);
          if (data.message) setPipelineMessage(data.message);
          if (data.bank_name && data.bank_name !== 'Auto-Detect' && data.bank_name !== 'Unknown') {
            setDetectedBank(data.bank_name);
          }
          if (data.applicant_name && data.applicant_name !== 'Auto-Detected' && data.applicant_name !== 'Unknown') {
            setDetectedApplicant(data.applicant_name);
          }

          if (data.status === 'success' || data.status === 'extraction_unverified' || data.status === 'analysis_incomplete') {
            clearInterval(interval);
            setPipelineProgress(100);
            setUploadState('success');
            setTimeout(() => {
              if (onUploadComplete) onUploadComplete(appId);
            }, 1200);
          } else if (data.status === 'failed') {
            clearInterval(interval);
            setUploadState('error');
            setErrorMessage(data.message || data.error || 'PDF Extraction failed. The document template might be unknown or columns misaligned. Please try manual calibration.');
          }
        }
      } catch (err) {
        console.error('Error polling status:', err);
      }
    }, 1000);
  };

  const handleSubmit = async (e) => {
    e.preventDefault();

    if (!files || files.length === 0) {
      alert('Please select at least one PDF statement file.');
      return;
    }

    const isMultiple = files.length > 1;
    setUploadState('uploading');
    setErrorMessage('');
    setPipelineProgress(15);
    setPipelineMessage(
      isMultiple 
        ? `Uploading ${files.length} statements for chronological merging...` 
        : 'Uploading PDF document to server...'
    );
    setBackendStatus('pending');
    setDetectedBank('');
    setDetectedApplicant('');

    const formData = new FormData();
    if (isMultiple) {
      files.forEach((f) => {
        formData.append('files', f);
      });
    } else {
      formData.append('file', files[0]);
    }

    formData.append('bank_name', bankName || 'Auto-Detect');
    formData.append('pdf_type', pdfType || 'digital');
    if (bankName === 'Other' && customBankName.trim()) {
      formData.append('custom_bank_name', customBankName.trim());
    }
    if (pdfPassword) {
      formData.append('pdf_password', pdfPassword);
    }

    try {
      const endpoint = isMultiple ? `${BACKEND_URL}/upload-multiple` : `${BACKEND_URL}/upload`;
      const response = await fetch(endpoint, {
        method: 'POST',
        body: formData,
      });

      if (response.ok) {
        const data = await response.json();
        setNeedsPassword(false);
        setPasswordHint('');
        setPdfPassword('');
        setCurrentAppId(data.application_id);
        setUploadState('processing');
        pollStatus(data.application_id);
      } else {
        const errorData = await response.json();
        // FastAPI nests a dict detail; a plain string detail is the older shape.
        const detail = errorData.detail;
        const status = typeof detail === 'object' && detail ? detail.status : null;
        const message =
          typeof detail === 'object' && detail
            ? detail.message
            : detail || 'An error occurred during upload.';

        if (status === 'password_required' || status === 'password_incorrect') {
          // Stay on the form with the files still selected so the user only has
          // to type the password, not re-pick the statements.
          setNeedsPassword(true);
          setPasswordHint(message);
          setUploadState('idle');
          setPdfPassword('');
          return;
        }

        setUploadState('error');
        setErrorMessage(message);
      }
    } catch (err) {
      console.error(err);
      setUploadState('error');
      setErrorMessage('Could not connect to backend server. Ensure it is running.');
    }
  };

  return (
    <div className="upload-card">
      <h3 className="upload-title">Process Bank Statement</h3>

      {uploadState === 'idle' && (
        <form onSubmit={handleSubmit}>
          <div
            className={`drag-drop-area ${dragActive ? 'active' : ''}`}
            onDragEnter={handleDrag}
            onDragOver={handleDrag}
            onDragLeave={handleDrag}
            onDrop={handleDrop}
            onClick={() => fileInputRef.current.click()}
          >
            <input
              type="file"
              ref={fileInputRef}
              style={{ display: 'none' }}
              accept=".pdf,application/pdf"
              multiple
              onChange={handleFileChange}
            />
            <Upload className="upload-icon" size={32} color="#3b82f6" />
            <p>
              Drag & drop one or multiple statement PDFs here, or{' '}
              <span className="file-input-label">browse files</span>
            </p>
            {files.length > 0 && (
              <div 
                className="selected-files-container" 
                onClick={(e) => e.stopPropagation()} 
                style={{ marginTop: '0.75rem', width: '100%', textAlign: 'left' }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.4rem' }}>
                  <span style={{ fontSize: '0.8rem', fontWeight: 600, color: 'var(--text-muted)' }}>
                    {files.length} statement{files.length > 1 ? 's' : ''} selected {files.length > 1 ? '• Chronological merge active' : ''}
                  </span>
                  <button
                    type="button"
                    onClick={(e) => { e.stopPropagation(); setFiles([]); }}
                    style={{ background: 'transparent', border: 'none', color: '#ef4444', fontSize: '0.75rem', cursor: 'pointer', padding: '2px 4px' }}
                  >
                    Clear all
                  </button>
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '0.35rem', maxHeight: '140px', overflowY: 'auto' }}>
                  {files.map((f, idx) => (
                    <div
                      key={`${f.name}-${idx}`}
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                        background: 'rgba(59, 130, 246, 0.08)',
                        border: '1px solid rgba(59, 130, 246, 0.2)',
                        borderRadius: '6px',
                        padding: '0.4rem 0.6rem',
                        fontSize: '0.8rem',
                      }}
                    >
                      <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: '240px', color: 'var(--text-main)', fontWeight: 500 }}>
                        📄 {f.name}
                      </span>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                        <span style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>
                          {(f.size / 1024).toFixed(1)} KB
                        </span>
                        <button
                          type="button"
                          onClick={(e) => removeFile(idx, e)}
                          style={{
                            background: 'transparent',
                            border: 'none',
                            color: '#94a3b8',
                            fontSize: '0.9rem',
                            lineHeight: '1',
                            cursor: 'pointer',
                            padding: '2px',
                          }}
                          title="Remove file"
                        >
                          ✕
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>

          {/* Shown only once the backend reports the statement is locked. The
              file stays selected, so the user types the password and resubmits
              rather than starting over. */}
          {needsPassword && (
            <div
              style={{
                marginTop: '1rem',
                padding: '0.9rem 1rem',
                border: '1.5px solid #f59e0b',
                borderRadius: '8px',
                background: 'rgba(245, 158, 11, 0.08)',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.6rem' }}>
                <AlertCircle size={18} color="#f59e0b" />
                <strong style={{ fontSize: '0.9rem', color: 'var(--text-main)' }}>
                  Password required
                </strong>
              </div>
              <p style={{ fontSize: '0.82rem', color: 'var(--text-muted)', margin: '0 0 0.7rem 0' }}>
                {passwordHint}
              </p>
              <input
                type="password"
                autoFocus
                value={pdfPassword}
                onChange={(e) => setPdfPassword(e.target.value)}
                placeholder="Statement password"
                aria-label="Statement password"
                style={{
                  width: '100%',
                  padding: '0.6rem 0.75rem',
                  borderRadius: '6px',
                  border: '1.5px solid #000000',
                  background: 'var(--input-bg)',
                  color: 'var(--text-main)',
                  fontSize: '0.9rem',
                }}
              />
              <p style={{ fontSize: '0.74rem', color: 'var(--text-muted)', margin: '0.55rem 0 0 0' }}>
                Used once to open this statement. It is not saved.
              </p>
            </div>
          )}

          <button type="submit" className="submit-btn" disabled={needsPassword && !pdfPassword}>
            {needsPassword 
              ? 'Unlock & Begin Extraction' 
              : files.length > 1 
                ? `Merge & Extract ${files.length} Statements` 
                : 'Begin Automated Extraction'}
          </button>
        </form>
      )}

      {(uploadState === 'uploading' || uploadState === 'processing') && (
        <div style={{ padding: '1rem 0.5rem' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '1rem' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
              <Loader className="placeholder-icon" size={26} color="var(--primary)" />
              <div>
                <h4 style={{ fontSize: '1.05rem', fontWeight: 700, margin: 0, color: 'var(--text-main)' }}>
                  Backend Pipeline Agent
                </h4>
                <p style={{ color: 'var(--text-muted)', fontSize: '0.825rem', marginTop: '0.2rem', marginBottom: 0 }}>
                  {pipelineMessage}
                </p>
              </div>
            </div>
            <span style={{ fontSize: '1.25rem', fontWeight: 800, color: 'var(--primary)', fontFamily: 'JetBrains Mono, monospace' }}>
              {pipelineProgress}%
            </span>
          </div>

          {/* Progress Bar */}
          <div style={{ width: '100%', height: '10px', background: 'var(--input-bg)', borderRadius: '999px', border: '1.5px solid #000000', overflow: 'hidden', marginBottom: '1.25rem' }}>
            <div
              style={{
                width: `${pipelineProgress}%`,
                height: '100%',
                background: 'linear-gradient(90deg, var(--primary), #3b82f6)',
                borderRadius: '999px',
                transition: 'width 0.4s ease-in-out'
              }}
            />
          </div>

          {/* Pipeline Checklist Status Card */}
          <div className="pipeline-checklist">
            <h5 className="pipeline-checklist-title">Pipeline Progress Status</h5>
            
            <div className="pipeline-steps-list">
              {/* Step 0: File Upload */}
              <div className={`pipeline-step-item ${
                uploadState === 'processing' || uploadState === 'success'
                  ? 'is-completed' 
                  : uploadState === 'uploading' 
                    ? 'is-active' 
                    : 'is-pending'
              }`}>
                <div className="pipeline-step-bullet">
                  {uploadState === 'processing' || uploadState === 'success' ? '✓' : '0'}
                </div>
                <div className="pipeline-step-content">
                  <div className="pipeline-step-label">File Upload Status</div>
                  <div className="pipeline-step-desc">
                    {uploadState === 'processing' || uploadState === 'success' ? (
                      <span className="pipeline-step-badge success">
                        Upload Completed
                      </span>
                    ) : uploadState === 'uploading' ? (
                      <span className="pipeline-step-loading">
                        Uploading {files.length > 1 ? `${files.length} statements` : (files[0]?.name || 'statement')}...
                      </span>
                    ) : 'Pending file selection'}
                  </div>
                </div>
              </div>

              {/* Step 1: Bank detection */}
              <div className={`pipeline-step-item ${
                (detectedBank || ['extracting', 'scoring', 'success'].includes(backendStatus)) 
                  ? 'is-completed' 
                  : (backendStatus === 'detecting' && !detectedBank) 
                    ? 'is-active' 
                    : 'is-pending'
              }`}>
                <div className="pipeline-step-bullet">
                  {(detectedBank || ['extracting', 'scoring', 'success'].includes(backendStatus)) ? '✓' : '1'}
                </div>
                <div className="pipeline-step-content">
                  <div className="pipeline-step-label">Bank Layout Detection</div>
                  <div className="pipeline-step-desc">
                    {detectedBank ? (
                      <span className="pipeline-step-badge success">
                        Bank Detected: <strong>{detectedBank}</strong>
                      </span>
                    ) : (backendStatus === 'detecting' && !detectedBank) ? (
                      <span className="pipeline-step-loading">Running pHash classification...</span>
                    ) : 'Pending file scan'}
                  </div>
                </div>
              </div>

              {/* Step 2: Name extraction */}
              <div className={`pipeline-step-item ${
                (detectedApplicant || ['extracting', 'scoring', 'success'].includes(backendStatus)) 
                  ? 'is-completed' 
                  : (backendStatus === 'detecting' && !detectedApplicant) 
                    ? 'is-active' 
                    : 'is-pending'
              }`}>
                <div className="pipeline-step-bullet">
                  {(detectedApplicant || ['extracting', 'scoring', 'success'].includes(backendStatus)) ? '✓' : '2'}
                </div>
                <div className="pipeline-step-content">
                  <div className="pipeline-step-label">Account Holder Name Extraction</div>
                  <div className="pipeline-step-desc">
                    {detectedApplicant ? (
                      <span className="pipeline-step-badge success">
                        Account Holder: <strong>{detectedApplicant}</strong>
                      </span>
                    ) : (backendStatus === 'detecting' && !detectedApplicant) ? (
                      <span className="pipeline-step-loading">Scanning header coordinates...</span>
                    ) : 'Pending bank layout classification'}
                  </div>
                </div>
              </div>

              {/* Step 3: Transaction extraction */}
              <div className={`pipeline-step-item ${
                ['scoring', 'success'].includes(backendStatus) 
                  ? 'is-completed' 
                  : backendStatus === 'extracting' 
                    ? 'is-active' 
                    : 'is-pending'
              }`}>
                <div className="pipeline-step-bullet">
                  {['scoring', 'success'].includes(backendStatus) ? '✓' : '3'}
                </div>
                <div className="pipeline-step-content">
                  <div className="pipeline-step-label">Extracting Transactions from PDF</div>
                  <div className="pipeline-step-desc">
                    {['scoring', 'success'].includes(backendStatus) ? (
                      <span className="pipeline-step-badge success">Transactions extracted successfully</span>
                    ) : backendStatus === 'extracting' ? (
                      <span className="pipeline-step-loading">Parsing tabular text blocks...</span>
                    ) : 'Waiting for name extraction'}
                  </div>
                </div>
              </div>

              {/* Step 4: Storing in DB & final validation */}
              <div className={`pipeline-step-item ${
                backendStatus === 'success' 
                  ? 'is-completed' 
                  : backendStatus === 'scoring' 
                    ? 'is-active' 
                    : 'is-pending'
              }`}>
                <div className="pipeline-step-bullet">
                  {backendStatus === 'success' ? '✓' : '4'}
                </div>
                <div className="pipeline-step-content">
                  <div className="pipeline-step-label">Database Storing & scoring validation</div>
                  <div className="pipeline-step-desc">
                    {backendStatus === 'success' ? (
                      <span className="pipeline-step-badge success">Saved in DB successfully</span>
                    ) : backendStatus === 'scoring' ? (
                      <span className="pipeline-step-loading">Validating columns and running scorecard analysis...</span>
                    ) : 'Waiting for transaction parsing'}
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {uploadState === 'success' && (
        <div style={{ textAlign: 'center', padding: '2rem' }}>
          <CheckCircle size={48} color="#10b981" style={{ margin: '0 auto 1.5rem auto' }} />
          <h4 style={{ fontSize: '1.2rem', color: '#10b981', marginBottom: '0.5rem' }}>
            Analysis Completed!
          </h4>
          <p style={{ color: 'var(--text-muted)', fontSize: '0.9rem' }}>
            The financial records were successfully cataloged. Redirecting to underwriting scorecard report...
          </p>
        </div>
      )}

      {uploadState === 'error' && (
        <div style={{ textAlign: 'center', padding: '2rem' }}>
          <AlertCircle size={48} color="#ef4444" style={{ margin: '0 auto 1.5rem auto' }} />
          <h4 style={{ fontSize: '1.2rem', color: '#ef4444', marginBottom: '0.5rem' }}>
            Pipeline Execution Failed
          </h4>
          <p style={{ color: 'var(--text-muted)', fontSize: '0.9rem', marginBottom: '1.5rem' }}>
            {errorMessage}
          </p>
          <button
            className="submit-btn"
            style={{ background: 'rgba(255,255,255,0.05)', color: 'var(--text-main)', border: '1px solid var(--border-color)', boxShadow: 'none' }}
            onClick={() => setUploadState('idle')}
          >
            Try Again
          </button>
        </div>
      )}
    </div>
  );
}
