import React, { useEffect, useState, useMemo, useRef, useCallback } from 'react';
import { FileText, Table, AlertTriangle, X, Search, ChevronLeft, ChevronRight, FileSpreadsheet, Download, Cpu, Bot, Send, Sparkles, ShieldCheck, Quote } from 'lucide-react';
import InfoTab from './InfoTab';
import './Copilot.css';

import { BACKEND_URL } from '../apiConfig';

const COPILOT_SUGGESTIONS = [
  'Check for high-interest fintech app loans (KreditBee, Fibe, Navi)',
  'Explain sudden balance drops or low balance days',
  'Analyze tax, GST, or statutory payments regularity',
  'Investigate large credit inflows > ₹1,00,000',
  'What is the true deflated turnover and FOIR?',
];

const copilotTime = () =>
  new Date().toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' });

export default function DetailsModal({ applicationId, onClose }) {
  const [activeTab, setActiveTab] = useState('scorecard');
  const [infoSubTab, setInfoSubTab] = useState('overview');
  const [loading, setLoading] = useState(true);
  const [result, setResult] = useState(null);
  const [transactions, setTransactions] = useState([]);

  // Underwriting Copilot State (BharatGen Param-Finance).
  //
  // The greeting is no longer seeded as a chat message. It was the only thing
  // in the stream on arrival, which made an empty conversation look like one
  // that had already started; it now renders as a welcome panel that the first
  // real message replaces.
  const [copilotMessages, setCopilotMessages] = useState([]);
  const [copilotInput, setCopilotInput] = useState('');
  const [copilotLoading, setCopilotLoading] = useState(false);
  const copilotStreamRef = useRef(null);
  const copilotInputRef = useRef(null);

  // Keep the newest message in view as the conversation grows.
  useEffect(() => {
    const el = copilotStreamRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [copilotMessages, copilotLoading]);

  const handleCopilotSend = useCallback(async (questionText) => {
    const q = (typeof questionText === 'string' ? questionText : copilotInput).trim();
    if (!q || copilotLoading) return;

    const newMsgs = [...copilotMessages, { sender: 'user', text: q, at: copilotTime() }];
    setCopilotMessages(newMsgs);
    setCopilotInput('');
    setCopilotLoading(true);

    try {
      const res = await fetch(`${BACKEND_URL}/api/copilot/query`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ application_id: applicationId, question: q })
      });
      if (res.ok) {
        const data = await res.json();
        setCopilotMessages([...newMsgs, {
          sender: 'copilot',
          text: data.answer,
          citations: data.citations || [],
          at: copilotTime()
        }]);
      } else {
        const err = await res.json().catch(() => ({}));
        const detail = err.detail;
        setCopilotMessages([...newMsgs, {
          sender: 'copilot',
          text: typeof detail === 'string'
            ? detail
            : (detail?.message || 'The Copilot could not process that question.'),
          isError: true,
          citations: [],
          at: copilotTime()
        }]);
      }
    } catch {
      setCopilotMessages([...newMsgs, {
        sender: 'copilot',
        text: 'Could not reach the Underwriting Copilot service. Check that the backend is running, then try again.',
        isError: true,
        citations: [],
        at: copilotTime()
      }]);
    } finally {
      setCopilotLoading(false);
    }
  }, [applicationId, copilotInput, copilotLoading, copilotMessages]);

  // Enter sends, Shift+Enter starts a new line.
  const handleCopilotKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleCopilotSend();
    }
  };

  const handleCopilotInput = (e) => {
    setCopilotInput(e.target.value);
    const el = e.target;
    el.style.height = 'auto';
    el.style.height = `${Math.min(el.scrollHeight, 120)}px`;
  };

  // Pagination & Search states to prevent tab freezing
  const [searchQuery, setSearchQuery] = useState('');
  const [txPage, setTxPage] = useState(1);
  const [txPageSize, setTxPageSize] = useState(999999);

  // Counterparty tagging. Some purposes are never written in the statement --
  // a fixed monthly NEFT to a co-operative bank is society maintenance, and the
  // bank truncated the payee before the PDF was written. Naming it once here
  // makes it stick for every statement that counterparty appears in.
  const [tagTarget, setTagTarget] = useState(null);
  const [tagSaving, setTagSaving] = useState(false);
  const [tagError, setTagError] = useState('');

  // CSV tab state
  const [csvData, setCsvData] = useState(null);
  const [csvLoading, setCsvLoading] = useState(false);
  const [csvError, setCsvError] = useState(null);
  const [csvSearchQuery, setCsvSearchQuery] = useState('');
  const [csvPage, setCsvPage] = useState(1);
  const [csvPageSize, setCsvPageSize] = useState(999999);

  useEffect(() => {
    if (!applicationId) return;

    const fetchData = async () => {
      setLoading(true);
      try {
        // Fetch Result
        const resResult = await fetch(`${BACKEND_URL}/result/${applicationId}`);
        if (resResult.ok) {
          const dataResult = await resResult.json();
          setResult(dataResult);
        }

        // Fetch Transactions
        const resTx = await fetch(`${BACKEND_URL}/applications/${applicationId}/transactions`);
        if (resTx.ok) {
          const dataTx = await resTx.json();
          setTransactions(dataTx.transactions || []);
        }
      } catch (error) {
        console.error('Error fetching application details:', error);
      } finally {
        setLoading(false);
      }
    };

    fetchData();
  }, [applicationId]);

  // Fetch CSV data when tab is activated
  useEffect(() => {
    if (activeTab !== 'csv' || !applicationId || csvData) return;

    const fetchCsv = async () => {
      setCsvLoading(true);
      setCsvError(null);
      try {
        const res = await fetch(`${BACKEND_URL}/transactions-csv/${applicationId}`);
        if (res.ok) {
          const data = await res.json();
          setCsvData(data);
        } else {
          const errData = await res.json().catch(() => ({}));
          setCsvError(errData.detail || `CSV not found (HTTP ${res.status})`);
        }
      } catch (error) {
        setCsvError('Could not connect to backend to fetch CSV data.');
        console.error('Error fetching CSV data:', error);
      } finally {
        setCsvLoading(false);
      }
    };

    fetchCsv();
  }, [activeTab, applicationId, csvData]);

  // Reset pagination when tab/search changes
  useEffect(() => {
    setTxPage(1);
  }, [searchQuery, activeTab]);

  useEffect(() => {
    setCsvPage(1);
  }, [csvSearchQuery]);

  const filteredTxs = useMemo(() => {
    if (!searchQuery.trim()) return transactions;
    const q = searchQuery.toLowerCase();
    return transactions.filter((tx) =>
      Object.values(tx).some((val) => String(val || '').toLowerCase().includes(q))
    );
  }, [transactions, searchQuery]);

  const totalPages = Math.max(1, Math.ceil(filteredTxs.length / txPageSize));
  const paginatedTxs = useMemo(() => {
    const start = (txPage - 1) * txPageSize;
    return filteredTxs.slice(start, start + txPageSize);
  }, [filteredTxs, txPage, txPageSize]);

  // CSV filtering & pagination
  const filteredCsvRows = useMemo(() => {
    if (!csvData?.rows) return [];
    if (!csvSearchQuery.trim()) return csvData.rows;
    const q = csvSearchQuery.toLowerCase();
    return csvData.rows.filter((row) =>
      Object.values(row).some((val) => String(val || '').toLowerCase().includes(q))
    );
  }, [csvData, csvSearchQuery]);

  const csvTotalPages = Math.max(1, Math.ceil(filteredCsvRows.length / csvPageSize));
  const paginatedCsvRows = useMemo(() => {
    const start = (csvPage - 1) * csvPageSize;
    return filteredCsvRows.slice(start, start + csvPageSize);
  }, [filteredCsvRows, csvPage, csvPageSize]);

  const TAG_OPTIONS = [
    ['Expense', 'Society / Property Tax', 'Need'],
    ['Expense', 'Rent', 'Need'],
    ['Expense', 'Loan / EMI', 'Need'],
    ['Expense', 'Insurance', 'Need'],
    ['Expense', 'Education', 'Need'],
    ['Expense', 'Healthcare', 'Need'],
    ['Expense', 'Grocery / Supermarket', 'Need'],
    ['Expense', 'Food Delivery', 'Want'],
    ['Expense', 'Shopping', 'Want'],
    ['Investment', 'Mutual Funds / SIP', 'Not Applicable'],
    ['Investment', 'PPF', 'Not Applicable'],
    ['Income', 'Salary', 'Not Applicable'],
    ['Income', 'Rent Received', 'Not Applicable'],
    ['Transfer', 'Family Support', 'Not Applicable'],
    ['Transfer', 'Self Transfer', 'Not Applicable'],
  ];

  const saveCounterpartyTag = async (option, scope) => {
    if (!tagTarget) return;
    const [category, subcategory, needsWants] = option;
    setTagSaving(true);
    setTagError('');
    try {
      const res = await fetch(`${BACKEND_URL}/counterparty-overrides`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          counterparty_key: tagTarget.counterparty_key,
          category,
          subcategory,
          needs_wants: needsWants,
          scope,
          applicant_id: scope === 'applicant' ? applicationId : null,
        }),
      });
      if (!res.ok) throw new Error(`Save failed (HTTP ${res.status})`);

      // Reflect the new label immediately; it applies in full on reprocessing.
      setTransactions((prev) => prev.map((t) =>
        t.counterparty_key === tagTarget.counterparty_key
          ? { ...t, category, subcategory, needs_wants: needsWants }
          : t));
      setTagTarget(null);
    } catch (err) {
      setTagError(err.message || 'Could not save the label.');
    } finally {
      setTagSaving(false);
    }
  };

  const handleDownloadCsv = () => {
    if (!applicationId) return;
    window.open(`${BACKEND_URL}/transactions-csv/${applicationId}/download`, '_blank');
  };

  // The classified rows -- every transaction with the category, subcategory,
  // needs/wants, counterparty and confidence the pipeline assigned. Distinct
  // from the raw extract above, which carries no labels at all.
  const handleDownloadFeaturesCsv = () => {
    if (!applicationId) return;
    window.open(`${BACKEND_URL}/features-csv/${applicationId}/download`, '_blank');
  };

  // The full multi-sheet workbook: the standard analysis views plus one sheet
  // per engine, the score breakdown and the verification report.
  const handleDownloadReport = () => {
    if (!applicationId) return;
    window.open(`${BACKEND_URL}/report-xlsx/${applicationId}/download`, '_blank');
  };

  if (!applicationId) return null;

  // Shared pagination controls component
  const PaginationControls = ({ currentPage, totalPagesVal, setPageFn, filteredLen, pageSize, label }) => (
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '0.5rem', borderTop: '1px solid var(--border-color)', paddingTop: '0.75rem', fontSize: '0.85rem' }}>
      <span style={{ color: 'var(--text-muted)' }}>
        {totalPagesVal <= 1 
          ? `Showing all ${filteredLen.toLocaleString()} ${label}`
          : `Showing ${((currentPage - 1) * pageSize + 1).toLocaleString()} to ${Math.min(currentPage * pageSize, filteredLen).toLocaleString()} of ${filteredLen.toLocaleString()} ${label}`}
      </span>
      {totalPagesVal > 1 && (
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <button
            disabled={currentPage <= 1}
            onClick={() => setPageFn(1)}
            style={{
              background: 'var(--input-bg)',
              border: '1px solid var(--border-color)',
              padding: '0.25rem 0.5rem',
              borderRadius: '0.35rem',
              cursor: currentPage <= 1 ? 'not-allowed' : 'pointer',
              opacity: currentPage <= 1 ? 0.5 : 1,
              color: 'var(--text-main)',
            }}
          >
            «
          </button>
          <button
            disabled={currentPage <= 1}
            onClick={() => setPageFn(p => Math.max(1, p - 1))}
            style={{
              display: 'flex',
              alignItems: 'center',
              background: 'var(--input-bg)',
              border: '1px solid var(--border-color)',
              padding: '0.25rem 0.5rem',
              borderRadius: '0.35rem',
              cursor: currentPage <= 1 ? 'not-allowed' : 'pointer',
              opacity: currentPage <= 1 ? 0.5 : 1,
              color: 'var(--text-main)',
            }}
          >
            <ChevronLeft size={16} />
          </button>
          <span style={{ fontWeight: 600, color: 'var(--text-main)', padding: '0 0.5rem' }}>
            Page {currentPage} of {totalPagesVal}
          </span>
          <button
            disabled={currentPage >= totalPagesVal}
            onClick={() => setPageFn(p => Math.min(totalPagesVal, p + 1))}
            style={{
              display: 'flex',
              alignItems: 'center',
              background: 'var(--input-bg)',
              border: '1px solid var(--border-color)',
              padding: '0.25rem 0.5rem',
              borderRadius: '0.35rem',
              cursor: currentPage >= totalPagesVal ? 'not-allowed' : 'pointer',
              opacity: currentPage >= totalPagesVal ? 0.5 : 1,
              color: 'var(--text-main)',
            }}
          >
            <ChevronRight size={16} />
          </button>
          <button
            disabled={currentPage >= totalPagesVal}
            onClick={() => setPageFn(totalPagesVal)}
            style={{
              background: 'var(--input-bg)',
              border: '1px solid var(--border-color)',
              padding: '0.25rem 0.5rem',
              borderRadius: '0.35rem',
              cursor: currentPage >= totalPagesVal ? 'not-allowed' : 'pointer',
              opacity: currentPage >= totalPagesVal ? 0.5 : 1,
              color: 'var(--text-main)',
            }}
          >
            »
          </button>
        </div>
      )}
    </div>
  );

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <div>
            <h3 style={{ fontSize: '1.4rem' }}>Analysis Report</h3>
            <p style={{ fontSize: '0.85rem', color: 'var(--text-muted)', marginTop: '0.25rem' }}>
              Application ID: {applicationId}
            </p>
          </div>
          {/* Kept in the header so the report is reachable from any tab, not
              only from the CSV view. */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <button
              className="csv-download-btn"
              onClick={handleDownloadFeaturesCsv}
              title="Feature extraction results as CSV"
            >
              <Download size={15} />
              <span>Feature CSV</span>
            </button>
            <button
              className="csv-download-btn"
              onClick={handleDownloadReport}
              title="Export Full Multi-Sheet Credit Appraisal Memo (CAM) Excel Report"
              style={{ background: 'var(--primary)', color: '#fff' }}
            >
              <FileSpreadsheet size={15} />
              <span>Export CAM (Excel)</span>
            </button>
            <button className="close-modal-btn" onClick={onClose}>
              <X size={24} />
            </button>
          </div>
        </div>

        <div className="modal-body">
          {loading ? (
            <div style={{ textAlign: 'center', padding: '4rem', color: 'var(--text-muted)' }}>
              Loading statement analysis data...
            </div>
          ) : !result ? (
            <div style={{ textAlign: 'center', padding: '4rem', color: 'var(--text-muted)' }}>
              Could not retrieve results. The application might still be processing.
            </div>
          ) : (
            <>
              {/* Modal Tabs */}
              <div className="modal-tabs">
                <button
                  className={`tab-btn ${activeTab === 'scorecard' ? 'active' : ''}`}
                  onClick={() => {
                    setActiveTab('scorecard');
                    setInfoSubTab('overview');
                  }}
                  title="Scorecard"
                >
                  <FileText size={18} style={{ display: 'inline', marginRight: '0.35rem', verticalAlign: 'text-bottom' }} />
                  <span className="hide-on-mobile">Scorecard</span>
                </button>
                <button
                  className={`tab-btn ${activeTab === 'features' ? 'active' : ''}`}
                  onClick={() => {
                    setActiveTab('features');
                    setInfoSubTab('features_extracted');
                  }}
                  title="Features Extracted"
                  style={{ borderColor: activeTab === 'features' ? 'var(--primary)' : 'transparent' }}
                >
                  <Cpu size={18} style={{ display: 'inline', marginRight: '0.35rem', verticalAlign: 'text-bottom', color: '#10b981' }} />
                  <span className="hide-on-mobile" style={{ fontWeight: 700 }}>Features Extracted</span>
                </button>
                <button
                  className={`tab-btn ${activeTab === 'transactions' ? 'active' : ''}`}
                  onClick={() => setActiveTab('transactions')}
                  title={`Transactions (${transactions.length})`}
                >
                  <Table size={18} style={{ display: 'inline', marginRight: '0.35rem', verticalAlign: 'text-bottom' }} />
                  <span className="hide-on-mobile">Transactions ({transactions.length})</span>
                </button>
                <button
                  className={`tab-btn ${activeTab === 'csv' ? 'active' : ''}`}
                  onClick={() => setActiveTab('csv')}
                  title="Extracted CSV"
                >
                  <FileSpreadsheet size={18} style={{ display: 'inline', marginRight: '0.35rem', verticalAlign: 'text-bottom' }} />
                  <span className="hide-on-mobile">Extracted CSV</span>
                </button>
                <button
                  className={`tab-btn ${activeTab === 'anomalies' ? 'active' : ''}`}
                  onClick={() => setActiveTab('anomalies')}
                  title="Anomalies & Insights"
                >
                  <AlertTriangle size={18} style={{ display: 'inline', marginRight: '0.35rem', verticalAlign: 'text-bottom' }} />
                  <span className="hide-on-mobile">Anomalies & Insights</span>
                </button>
                <button
                  className={`tab-btn ${activeTab === 'copilot' ? 'active' : ''}`}
                  onClick={() => setActiveTab('copilot')}
                  title="Ask Copilot (BharatGen Param-Finance AI)"
                  style={{
                    borderBottom: activeTab === 'copilot' ? '2px solid #818cf8' : 'none',
                    background: activeTab === 'copilot' ? 'rgba(99, 102, 241, 0.15)' : 'transparent',
                  }}
                >
                  <Bot size={18} style={{ display: 'inline', marginRight: '0.35rem', verticalAlign: 'text-bottom', color: '#818cf8' }} />
                  <span className="hide-on-mobile" style={{ color: activeTab === 'copilot' ? '#a5b4fc' : 'inherit', fontWeight: 600 }}>
                    Ask Copilot (AI)
                  </span>
                </button>
              </div>

              {/* Scorecard Tab */}
              {activeTab === 'scorecard' && (
                <InfoTab result={result} initialSubTab="overview" />
              )}

              {/* Features Extracted Tab */}
              {activeTab === 'features' && (
                <InfoTab result={result} initialSubTab="features_extracted" />
              )}

              {/* Transactions Tab */}
              {activeTab === 'transactions' && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
                  {/* Search and Page Size controls */}
                  <div style={{ display: 'flex', justifyContent: 'space-between', gap: '1rem', flexWrap: 'wrap' }}>
                    <div style={{ position: 'relative', flex: 1, minWidth: '200px' }}>
                      <Search size={16} style={{ position: 'absolute', left: '0.75rem', top: '50%', transform: 'translateY(-50%)', color: 'var(--text-muted)' }} />
                      <input
                        type="text"
                        placeholder="Search transactions..."
                        value={searchQuery}
                        onChange={(e) => setSearchQuery(e.target.value)}
                        style={{
                          width: '100%',
                          padding: '0.5rem 1rem 0.5rem 2.25rem',
                          background: 'var(--input-bg)',
                          border: '1px solid var(--border-color)',
                          borderRadius: '0.5rem',
                          fontSize: '0.85rem',
                          color: 'var(--text-main)',
                          outline: 'none',
                        }}
                      />
                    </div>
                  </div>

                  <div className="data-table-container" style={{ maxHeight: '400px', overflowY: 'auto' }}>
                    <table className="data-table">
                      <thead style={{ position: 'sticky', top: 0, background: '#0b1329', zIndex: 10 }}>
                        <tr>
                          <th>Date</th>
                          <th>Description</th>
                          <th style={{ textAlign: 'right' }}>Debit (Dr)</th>
                          <th style={{ textAlign: 'right' }}>Credit (Cr)</th>
                          <th style={{ textAlign: 'right' }}>Balance</th>
                          <th>Category</th>
                          <th>Counterparty</th>
                        </tr>
                      </thead>
                      <tbody>
                        {filteredTxs.length === 0 ? (
                          <tr>
                            <td colSpan="7" style={{ textAlign: 'center', padding: '2rem', color: 'var(--text-muted)' }}>
                              No transactions match search criteria.
                            </td>
                          </tr>
                        ) : (
                          paginatedTxs.map((tx, idx) => (
                            <tr key={idx}>
                              <td>{tx.date}</td>
                              <td style={{ fontSize: '0.85rem', maxWidth: '300px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={tx.description}>
                                {tx.description}
                              </td>
                              <td style={{ textAlign: 'right', color: tx.debit > 0 ? '#ff7878' : 'inherit' }}>
                                {tx.debit > 0 ? `₹ ${Number(tx.debit).toFixed(2)}` : '-'}
                              </td>
                              <td style={{ textAlign: 'right', color: tx.credit > 0 ? '#78ff78' : 'inherit' }}>
                                {tx.credit > 0 ? `₹ ${Number(tx.credit).toFixed(2)}` : '-'}
                              </td>
                              <td style={{ textAlign: 'right', fontWeight: 600 }}>
                                ₹ {tx.balance ? Number(tx.balance).toFixed(2) : '0.00'}
                              </td>
                              <td style={{ fontSize: '0.8rem' }} title={tx.suggestion_reason || ''}>
                                {tx.subcategory || '—'}
                                {tx.recurrence_type && tx.recurrence_type !== 'IRREGULAR' && (
                                  <span style={{ marginLeft: '0.35rem', fontSize: '0.65rem', opacity: 0.7 }}>
                                    ({tx.recurrence_type.toLowerCase()})
                                  </span>
                                )}
                              </td>
                              <td style={{ fontSize: '0.8rem' }}>
                                {tx.counterparty_key ? (
                                  <button
                                    type="button"
                                    onClick={() => setTagTarget(tx)}
                                    title={`Tell the system what "${tx.counterparty_key}" is. The label applies to every statement this counterparty appears in.`}
                                    style={{
                                      background: 'transparent', border: '1px dashed var(--border-color)',
                                      borderRadius: '0.35rem', padding: '0.15rem 0.4rem',
                                      color: 'var(--text-main)', cursor: 'pointer', fontSize: '0.72rem',
                                    }}
                                  >
                                    {tx.counterparty_key.split('|')[0].slice(0, 18)} ✎
                                  </button>
                                ) : (
                                  <span style={{ color: 'var(--text-muted)' }}>—</span>
                                )}
                              </td>
                            </tr>
                          ))
                        )}
                      </tbody>
                    </table>
                  </div>

                  {/* Pagination Controls */}
                  {filteredTxs.length > 0 && (
                    <PaginationControls
                      currentPage={txPage}
                      totalPagesVal={totalPages}
                      setPageFn={setTxPage}
                      filteredLen={filteredTxs.length}
                      pageSize={txPageSize}
                      label="transactions"
                    />
                  )}
                </div>
              )}

              {/* Extracted CSV Tab */}
              {activeTab === 'csv' && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
                  {csvLoading ? (
                    <div style={{ textAlign: 'center', padding: '4rem', color: 'var(--text-muted)' }}>
                      <div className="csv-loading-spinner" />
                      <p style={{ marginTop: '1rem' }}>Loading extracted CSV data...</p>
                    </div>
                  ) : csvError ? (
                    <div className="csv-empty-state">
                      <FileSpreadsheet size={48} style={{ color: 'var(--text-muted)', opacity: 0.4 }} />
                      <p style={{ color: 'var(--text-muted)', fontSize: '0.95rem', marginTop: '1rem' }}>{csvError}</p>
                      <p style={{ color: 'var(--text-muted)', fontSize: '0.8rem', opacity: 0.7 }}>
                        Upload and process a bank statement to generate the transaction CSV.
                      </p>
                    </div>
                  ) : csvData ? (
                    <>
                      {/* CSV Metadata Header */}
                      <div className="csv-meta-bar">
                        <div className="csv-meta-badges">
                          <span className="csv-meta-badge file">
                            <FileSpreadsheet size={14} />
                            {csvData.csv_filename}
                          </span>
                          <span className="csv-meta-badge rows">
                            {csvData.total_rows.toLocaleString()} rows
                          </span>
                          <span className="csv-meta-badge cols">
                            {csvData.columns.length} columns
                          </span>
                          <span className="csv-meta-badge bank">
                            {csvData.bank_name}
                          </span>
                        </div>
                        <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
                          <button
                            className="csv-download-btn"
                            onClick={handleDownloadCsv}
                            title="The raw extracted rows, before classification"
                          >
                            <Download size={15} />
                            <span>Raw CSV</span>
                          </button>
                          <button
                            className="csv-download-btn"
                            onClick={handleDownloadFeaturesCsv}
                            title="Every transaction with its category, subcategory, needs/wants, counterparty and confidence"
                          >
                            <Download size={15} />
                            <span>Feature Results CSV</span>
                          </button>
                          <button
                            className="csv-download-btn"
                            onClick={handleDownloadReport}
                            title="Full multi-sheet analysis workbook, including a sheet per engine"
                            style={{ background: 'var(--primary)', color: '#fff' }}
                          >
                            <FileSpreadsheet size={15} />
                            <span>Excel Report</span>
                          </button>
                        </div>
                      </div>

                      {/* Search + Page Size */}
                      <div style={{ display: 'flex', justifyContent: 'space-between', gap: '1rem', flexWrap: 'wrap' }}>
                        <div style={{ position: 'relative', flex: 1, minWidth: '200px' }}>
                          <Search size={16} style={{ position: 'absolute', left: '0.75rem', top: '50%', transform: 'translateY(-50%)', color: 'var(--text-muted)' }} />
                          <input
                            type="text"
                            placeholder="Search CSV rows..."
                            value={csvSearchQuery}
                            onChange={(e) => setCsvSearchQuery(e.target.value)}
                            style={{
                              width: '100%',
                              padding: '0.5rem 1rem 0.5rem 2.25rem',
                              background: 'var(--input-bg)',
                              border: '1px solid var(--border-color)',
                              borderRadius: '0.5rem',
                              fontSize: '0.85rem',
                              color: 'var(--text-main)',
                              outline: 'none',
                            }}
                          />
                        </div>
                      </div>

                      {/* CSV Data Table */}
                      <div className="data-table-container csv-table-container" style={{ maxHeight: '420px', overflowY: 'auto', overflowX: 'auto' }}>
                        <table className="data-table csv-data-table">
                          <thead style={{ position: 'sticky', top: 0, zIndex: 10 }}>
                            <tr>
                              <th className="csv-row-num-col">#</th>
                              {csvData.columns.map((col, i) => (
                                <th key={i} className="csv-col-header">{col}</th>
                              ))}
                            </tr>
                          </thead>
                          <tbody>
                            {filteredCsvRows.length === 0 ? (
                              <tr>
                                <td colSpan={csvData.columns.length + 1} style={{ textAlign: 'center', padding: '2rem', color: 'var(--text-muted)' }}>
                                  No rows match search criteria.
                                </td>
                              </tr>
                            ) : (
                              paginatedCsvRows.map((row, rowIdx) => {
                                const globalIdx = (csvPage - 1) * csvPageSize + rowIdx + 1;
                                return (
                                  <tr key={rowIdx}>
                                    <td className="csv-row-num">{globalIdx}</td>
                                    {csvData.columns.map((col, colIdx) => {
                                      const val = row[col] || '';
                                      // Detect numeric values for right-alignment
                                      const isNumeric = val !== '' && !isNaN(val) && val.trim() !== '';
                                      // Detect debit/credit columns for coloring
                                      const colLower = col.toLowerCase();
                                      const isDebit = colLower.includes('debit') || colLower === 'dr';
                                      const isCredit = colLower.includes('credit') || colLower === 'cr';
                                      const isBalance = colLower.includes('balance') || colLower === 'bal';
                                      
                                      let cellColor = 'inherit';
                                      if (isNumeric && parseFloat(val) > 0) {
                                        if (isDebit) cellColor = '#ff7878';
                                        else if (isCredit) cellColor = '#78ff78';
                                      }

                                      return (
                                        <td
                                          key={colIdx}
                                          style={{
                                            textAlign: isNumeric ? 'right' : 'left',
                                            color: cellColor,
                                            fontWeight: isBalance && isNumeric ? 600 : 'normal',
                                            maxWidth: '300px',
                                            overflow: 'hidden',
                                            textOverflow: 'ellipsis',
                                            whiteSpace: 'nowrap',
                                          }}
                                          title={val}
                                        >
                                          {isNumeric && (isDebit || isCredit || isBalance) && parseFloat(val) > 0
                                            ? `₹ ${Number(val).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
                                            : val || '-'}
                                        </td>
                                      );
                                    })}
                                  </tr>
                                );
                              })
                            )}
                          </tbody>
                        </table>
                      </div>

                      {/* Pagination */}
                      {filteredCsvRows.length > 0 && (
                        <PaginationControls
                          currentPage={csvPage}
                          totalPagesVal={csvTotalPages}
                          setPageFn={setCsvPage}
                          filteredLen={filteredCsvRows.length}
                          pageSize={csvPageSize}
                          label="rows"
                        />
                      )}
                    </>
                  ) : null}
                </div>
              )}

              {/* Anomalies Tab */}
              {/* This tab used to read result.metadata.irregular_credits and
                  .negative_balance_months -- neither of which the pipeline has
                  ever produced. Both were therefore always empty, so the tab
                  unconditionally printed "No irregular credit patterns detected"
                  and "Balance remained positive", including for accounts the
                  fraud engine had flagged. It now reads the engines' real
                  output. */}
              {activeTab === 'anomalies' && (() => {
                const meta = typeof result.metadata === 'string'
                  ? (() => { try { return JSON.parse(result.metadata); } catch { return {}; } })()
                  : (result.metadata || {});
                const src = meta.features_summary || meta;
                const fraud = src?.fraud || {};
                const balance = src?.balance || {};
                const events = Array.isArray(fraud.fraud_events) ? fraud.fraud_events : [];
                const negativeDays = balance.negative_balance_count;

                return (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
                    {/* Top Overview Ribbon */}
                    <div style={{
                      display: 'grid',
                      gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))',
                      gap: '0.75rem',
                    }}>
                      <div style={{ background: 'var(--input-bg)', border: '1px solid var(--border-color)', borderRadius: '0.5rem', padding: '0.85rem' }}>
                        <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>AML Risk Band</div>
                        <div style={{ fontSize: '1.05rem', fontWeight: 700, marginTop: '0.2rem', color: String(fraud.aml_risk_band).toUpperCase() === 'CRITICAL' || String(fraud.aml_risk_band).toUpperCase() === 'HIGH' ? '#ef4444' : '#10b981' }}>
                          {fraud.aml_risk_band || 'LOW'}
                        </div>
                      </div>
                      <div style={{ background: 'var(--input-bg)', border: '1px solid var(--border-color)', borderRadius: '0.5rem', padding: '0.85rem' }}>
                        <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Fraud Risk Score</div>
                        <div style={{ fontSize: '1.05rem', fontWeight: 700, marginTop: '0.2rem' }}>
                          {fraud.fraud_score != null ? `${Number(fraud.fraud_score).toFixed(1)} / 100` : '0.0 / 100'}
                        </div>
                      </div>
                      <div style={{ background: 'var(--input-bg)', border: '1px solid var(--border-color)', borderRadius: '0.5rem', padding: '0.85rem' }}>
                        <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Irregularity Penalties</div>
                        <div style={{ fontSize: '1.05rem', fontWeight: 700, marginTop: '0.2rem', color: Number(fraud.irregularity_penalty_points || 0) > 0 ? '#ef4444' : '#10b981' }}>
                          {Number(fraud.irregularity_penalty_points || 0) > 0 ? `-${fraud.irregularity_penalty_points} pts` : '0 pts'}
                        </div>
                      </div>
                      <div style={{ background: 'var(--input-bg)', border: '1px solid var(--border-color)', borderRadius: '0.5rem', padding: '0.85rem' }}>
                        <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Flags Triggered</div>
                        <div style={{ fontSize: '1.05rem', fontWeight: 700, marginTop: '0.2rem' }}>
                          {events.length} flagged
                        </div>
                      </div>
                    </div>

                    <div className="info-group">
                      <h4>Irregularities &amp; Behavioral Flags</h4>
                      {events.length > 0 ? (
                        <div className="data-table-container" style={{ maxHeight: '350px', overflowY: 'auto' }}>
                          <table className="data-table" style={{ fontSize: '0.85rem' }}>
                            <thead>
                              <tr>
                                <th style={{ width: '30%' }}>Rule</th>
                                <th style={{ width: '15%' }}>Severity</th>
                                <th style={{ width: '55%' }}>Detail</th>
                              </tr>
                            </thead>
                            <tbody>
                              {events.map((ev, i) => {
                                const sev = String(ev.severity || 'LOW').toUpperCase();
                                const badgeClass = (sev === 'CRITICAL' || sev === 'HIGH')
                                  ? 'status-badge failed'
                                  : sev === 'MEDIUM'
                                  ? 'status-badge pending'
                                  : 'status-badge success';
                                return (
                                  <tr key={i}>
                                    <td style={{ fontWeight: 600 }}>{ev.rule || ev.rule_name}</td>
                                    <td>
                                      <span className={badgeClass}>
                                        {sev}
                                      </span>
                                    </td>
                                    <td style={{ color: 'var(--text-muted)', lineHeight: '1.4' }}>
                                      {ev.explanation}
                                    </td>
                                  </tr>
                                );
                              })}
                            </tbody>
                          </table>
                        </div>
                      ) : (
                        <p style={{ color: 'var(--text-muted)', fontSize: '0.9rem', margin: '0.5rem 0' }}>
                          ✓ No irregular transactions or fraud patterns detected in this statement.
                        </p>
                      )}
                    </div>

                    <div className="info-group">
                      <h4>Balance &amp; Account Health</h4>
                      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '0.75rem', marginTop: '0.5rem' }}>
                        <div className="info-item" style={{ borderBottom: 'none' }}>
                          <span className="info-label">Negative Balance Days</span>
                          <span className={negativeDays > 0 ? 'status-badge failed' : 'status-badge success'}>
                            {negativeDays > 0 ? `${negativeDays} days` : '0 days (Clean)'}
                          </span>
                        </div>
                        {balance.lowest_balance != null && (
                          <div className="info-item" style={{ borderBottom: 'none' }}>
                            <span className="info-label">Lowest Balance</span>
                            <span className="info-value">
                              ₹ {Number(balance.lowest_balance).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                            </span>
                          </div>
                        )}
                        {balance.highest_balance != null && (
                          <div className="info-item" style={{ borderBottom: 'none' }}>
                            <span className="info-label">Highest Balance</span>
                            <span className="info-value">
                              ₹ {Number(balance.highest_balance).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                            </span>
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                );
              })()}

              {/* Underwriting Copilot Tab */}
              {activeTab === 'copilot' && (
                <div className="copilot">
                  {/* Institutional header banner */}
                  <div className="copilot-banner">
                    <div className="copilot-banner-id">
                      <div className="copilot-avatar">
                        <Bot size={20} />
                      </div>
                      <div style={{ minWidth: 0 }}>
                        <div className="copilot-title">
                          BharatGen Param-Finance
                          <span className="copilot-chip">SOVEREIGN BFSI AI</span>
                        </div>
                        <div className="copilot-subtitle">
                          Answers are grounded in this statement&apos;s ledger rows, with figures locked to the verified scorecard.
                        </div>
                      </div>
                    </div>
                    <div className="copilot-guardrails">
                      <ShieldCheck size={14} />
                      <span>5 BFSI guardrails active</span>
                    </div>
                  </div>

                  {/* Message stream */}
                  <div className="copilot-stream" ref={copilotStreamRef}>
                    {copilotMessages.length === 0 && !copilotLoading && (
                      <div className="copilot-welcome">
                        <div className="copilot-welcome-icon">
                          <Sparkles size={24} />
                        </div>
                        <h4>Ask about this statement</h4>
                        <p>
                          Every answer cites the transaction rows it came from, so you can
                          verify each claim against the ledger. Start with one of these, or
                          ask your own question.
                        </p>
                        <div className="copilot-suggestions">
                          {COPILOT_SUGGESTIONS.map((prompt) => (
                            <button
                              key={prompt}
                              type="button"
                              className="copilot-suggest"
                              disabled={copilotLoading}
                              onClick={() => handleCopilotSend(prompt)}
                            >
                              {prompt}
                            </button>
                          ))}
                        </div>
                      </div>
                    )}

                    {copilotMessages.map((msg, mIdx) => {
                      const isUser = msg.sender === 'user';
                      return (
                        <div
                          key={mIdx}
                          className={`copilot-row ${isUser ? 'is-user' : 'is-copilot'}`}
                        >
                          <div className="copilot-row-avatar">
                            {isUser ? 'YOU' : <Bot size={15} />}
                          </div>
                          <div className="copilot-body">
                            <div className="copilot-meta">
                              <span>{isUser ? 'Credit officer' : 'Param-Finance'}</span>
                              {msg.at && <span style={{ fontWeight: 400 }}>· {msg.at}</span>}
                            </div>

                            <div className={`copilot-bubble ${msg.isError ? 'is-error' : ''}`}>
                              {msg.text}
                            </div>

                            {msg.citations && msg.citations.length > 0 && (
                              <div className="copilot-citations">
                                <div className="copilot-citations-head">
                                  <Quote size={11} />
                                  <span>
                                    {msg.citations.length} verified transaction
                                    {msg.citations.length === 1 ? '' : 's'}
                                  </span>
                                </div>
                                {msg.citations.map((c, cIdx) => (
                                  <div className="copilot-citation" key={cIdx}>
                                    <span className="copilot-citation-date">{c.date || '—'}</span>
                                    <span className="copilot-citation-text" title={c.narration || ''}>
                                      {c.narration || '—'}
                                    </span>
                                    <span className="copilot-citation-amt">
                                      {Number.isFinite(Number(c.amount))
                                        ? `₹${Number(c.amount).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
                                        : '—'}
                                    </span>
                                  </div>
                                ))}
                              </div>
                            )}
                          </div>
                        </div>
                      );
                    })}

                    {copilotLoading && (
                      <div className="copilot-row is-copilot">
                        <div className="copilot-row-avatar">
                          <Bot size={15} />
                        </div>
                        <div className="copilot-body">
                          <div className="copilot-meta">
                            <span>Param-Finance</span>
                            <span style={{ fontWeight: 400 }}>· inspecting ledger</span>
                          </div>
                          <div className="copilot-bubble" style={{ padding: 0 }}>
                            <div className="copilot-typing" aria-label="Copilot is thinking">
                              <span /><span /><span />
                            </div>
                          </div>
                        </div>
                      </div>
                    )}
                  </div>

                  {/* Follow-up chips, once the conversation is under way */}
                  {copilotMessages.length > 0 && (
                    <div>
                      <div className="copilot-suggest-label">
                        <Sparkles size={12} />
                        <span>Follow up with</span>
                      </div>
                      <div className="copilot-suggestions is-inline">
                        {COPILOT_SUGGESTIONS.slice(0, 3).map((prompt) => (
                          <button
                            key={prompt}
                            type="button"
                            className="copilot-suggest"
                            disabled={copilotLoading}
                            onClick={() => handleCopilotSend(prompt)}
                          >
                            {prompt}
                          </button>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Composer */}
                  <div>
                    <div className="copilot-composer">
                      <textarea
                        ref={copilotInputRef}
                        rows={1}
                        placeholder="Ask about a transaction, a lender, a balance drop, a category…"
                        value={copilotInput}
                        onChange={handleCopilotInput}
                        onKeyDown={handleCopilotKeyDown}
                        disabled={copilotLoading}
                        aria-label="Ask the Underwriting Copilot"
                      />
                      <button
                        type="button"
                        className="copilot-send"
                        onClick={() => handleCopilotSend()}
                        disabled={copilotLoading || !copilotInput.trim()}
                        aria-label="Send question"
                        title="Send (Enter)"
                      >
                        <Send size={16} />
                      </button>
                    </div>
                    <div className="copilot-hint" style={{ marginTop: '0.45rem' }}>
                      Enter to send · Shift + Enter for a new line
                    </div>
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      </div>

      {/* Counterparty tagging dialog */}
      {tagTarget && (
        <div
          onClick={(e) => { e.stopPropagation(); setTagTarget(null); }}
          style={{
            position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.55)',
            display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 100,
          }}
        >
          <div
            onClick={(e) => e.stopPropagation()}
            style={{
              background: 'var(--card-bg, #0b1329)', border: '1px solid var(--border-color)',
              borderRadius: '0.75rem', padding: '1.25rem', width: 'min(520px, 92vw)',
              maxHeight: '80vh', overflowY: 'auto',
            }}
          >
            <h4 style={{ margin: '0 0 0.25rem' }}>What is this counterparty?</h4>
            <p style={{ color: 'var(--text-muted)', fontSize: '0.82rem', marginTop: 0 }}>
              The statement does not say — banks truncate the payee name before the PDF is
              written. Name it once and the label applies wherever it appears.
            </p>

            <div style={{
              background: 'var(--input-bg)', borderRadius: '0.5rem',
              padding: '0.6rem 0.75rem', margin: '0.75rem 0', fontSize: '0.82rem',
            }}>
              <div style={{ fontWeight: 700 }}>{tagTarget.counterparty_key}</div>
              <div style={{ color: 'var(--text-muted)', marginTop: '0.2rem' }}>
                {tagTarget.description}
              </div>
              {tagTarget.suggestion_reason && (
                <div style={{ color: '#f0b429', marginTop: '0.35rem' }}>
                  Observed pattern: {tagTarget.suggestion_reason}
                </div>
              )}
            </div>

            {tagError && (
              <div style={{ color: '#ef4444', fontSize: '0.8rem', marginBottom: '0.5rem' }}>
                {tagError}
              </div>
            )}

            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.4rem' }}>
              {TAG_OPTIONS.map((opt) => (
                <button
                  key={opt[1]}
                  type="button"
                  disabled={tagSaving}
                  onClick={() => saveCounterpartyTag(opt, 'global')}
                  style={{
                    background: 'var(--input-bg)', border: '1px solid var(--border-color)',
                    borderRadius: '0.4rem', padding: '0.35rem 0.6rem',
                    color: 'var(--text-main)', cursor: tagSaving ? 'wait' : 'pointer',
                    fontSize: '0.78rem',
                  }}
                >
                  {opt[1]}
                </button>
              ))}
            </div>

            <div style={{
              display: 'flex', justifyContent: 'space-between', alignItems: 'center',
              marginTop: '1rem', fontSize: '0.75rem', color: 'var(--text-muted)',
            }}>
              <span>Saved for every applicant. Reprocess to apply it to the totals.</span>
              <button
                type="button"
                onClick={() => setTagTarget(null)}
                style={{
                  background: 'transparent', border: '1px solid var(--border-color)',
                  borderRadius: '0.4rem', padding: '0.3rem 0.7rem',
                  color: 'var(--text-main)', cursor: 'pointer',
                }}
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
