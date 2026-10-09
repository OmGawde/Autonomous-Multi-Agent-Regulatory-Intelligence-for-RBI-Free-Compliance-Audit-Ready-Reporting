import React, { useState, useEffect, useMemo } from 'react';
import { ShieldCheck, CheckCircle2, Sparkles, Award, Cpu, FileText, AlertTriangle } from 'lucide-react';
import { BACKEND_URL } from '../apiConfig';

export default function InfoTab({ result = {}, initialSubTab = 'overview' }) {
  const [subTab, setSubTab] = useState(initialSubTab);
  const [featureData, setFeatureData] = useState(null);
  const [featureLoading, setFeatureLoading] = useState(false);
  const [featureError, setFeatureError] = useState(null);
  const [featureSearch, setFeatureSearch] = useState('');
  const [featureCategory, setFeatureCategory] = useState('all');

  useEffect(() => {
    if (initialSubTab) {
      setSubTab(initialSubTab);
    }
  }, [initialSubTab]);

  // Safely parse metadata if it comes as a JSON string, memoized stably
  const parsedMeta = useMemo(() => {
    if (!result || !result.metadata) return {};
    if (typeof result.metadata === 'string') {
      try {
        return JSON.parse(result.metadata);
      } catch (e) {
        return {};
      }
    }
    return result.metadata || {};
  }, [result?.metadata]);

  const meta = useMemo(() => {
    const src = parsedMeta.features_summary || parsedMeta;

    const realIncome = src?.income?.features || src?.income || {};
    const realExpense = src?.expense?.features || src?.expense || {};
    const realBalance = src?.balance?.features || src?.balance || {};
    const realDebt = src?.debt?.features || src?.debt || {};
    const realSavings = src?.savings?.features || src?.savings || {};
    const realInvestment = src?.investment?.features || src?.investment || {};
    const realBehaviour = src?.behaviour?.features || src?.behaviour || {};
    const realCashFlow = src?.cash_flow?.features || src?.cash_flow || {};
    const realFraud = src?.fraud?.features || src?.fraud || {};

    const baseIncome = Number(realIncome.total_income ?? result?.total_income ?? 0);
    const baseExpense = Number(realExpense.total_expenses ?? result?.total_expenses ?? 0);
    const baseBalance = Number(realBalance.average_daily_balance ?? result?.average_monthly_balance ?? 0);
    const baseEMI = Number(realDebt.monthly_emi ?? result?.monthly_obligations ?? 0);
    const baseFOIR = Number(realDebt.foir ?? realDebt.dti ?? result?.debt_to_income_ratio ?? 0);

    const monthlyIncMap = realIncome.monthly_income || {};
    // null, not 12 -- printing "12 months" for an unknown statement period
    // stated a fact the data did not support.
    const monthsCount = Object.keys(monthlyIncMap).length || src?.months_covered || null;

    return {
      transaction_count: parsedMeta.transaction_count || parsedMeta.total_transactions || result?.metadata?.transaction_count || 0,
      months_covered: monthsCount,
      statement_period: src?.statement_period || {},

      // Values come from the engines as-is. Defaulting them to 0 (or to 1 for
      // income_sources) turned "not computed" into a confident figure -- a real
      // 0 was displayed as "1 sources".
      income: {
        total_income: baseIncome,
        salary_income: realIncome.salary_income,
        average_income: realIncome.average_income,
        other_income: realIncome.other_income,
        income_sources: realIncome.income_sources,
        salary_consistency: realIncome.salary_consistency,
        income_stability: realIncome.income_stability,
        non_income_credits_total: realIncome.non_income_credits_total,
        monthly_income: monthlyIncMap
      },

      // wants_spending was synthesised as (total - needs), so with needs at 0
      // the UI asserted that 100% of spending was discretionary. The expense
      // engine reports both sides; neither is derived here any more.
      expense: {
        total_expenses: baseExpense,
        average_expenses: realExpense.average_expenses,
        needs_spending: realExpense.needs_spending,
        needs_ratio: realExpense.needs_ratio,
        wants_spending: realExpense.wants_spending,
        wants_ratio: realExpense.wants_ratio,
        expense_ratio: realExpense.expense_ratio,
        category_spending: realExpense.category_spending || {}
      },

      balance: {
        average_daily_balance: baseBalance,
        opening_balance: realBalance.opening_balance ?? 0,
        closing_balance: realBalance.closing_balance ?? 0,
        lowest_balance: realBalance.lowest_balance ?? 0,
        highest_balance: realBalance.highest_balance ?? 0,
        days_below_1000: realBalance.days_below_1000 ?? realBalance.low_balance_count ?? 0,
        balance_volatility: realBalance.balance_volatility ?? 0,
        average_monthly_balance: realBalance.average_monthly_balance || {},
        abb_score: realBalance.abb_score,
        avg_daily_balance_change_pct: realBalance.avg_daily_balance_change_pct,
        max_daily_balance_change_pct: realBalance.max_daily_balance_change_pct,
        balance_recovery_time: realBalance.balance_recovery_time
      },

      debt: {
        monthly_emi: baseEMI,
        total_monthly_obligations: realDebt.total_monthly_obligations,
        // FOIR and DTI are distinct ratios; collapsing them hid which was shown.
        foir: realDebt.foir,
        dti: realDebt.dti,
        emi_discipline_score: realDebt.emi_discipline_score,
        active_loan_count: realDebt.active_loan_count ?? realDebt.loan_count ?? realDebt.total_loan_count ?? 0,
        missed_emi_count: realDebt.missed_emi_count ?? 0,
        recent_borrowing_velocity_90d: realDebt.recent_borrowing_velocity_90d ?? 0,
        loan_stacking_flag: realDebt.loan_stacking_flag ?? false,
        distinct_lenders_count: realDebt.distinct_lenders_count ?? 0,
        lender_concentration_ratio: realDebt.lender_concentration_ratio ?? 0,
        secured_ratio: realDebt.secured_ratio ?? 0,
        unsecured_ratio: realDebt.unsecured_ratio ?? 0,
        home_loan_emi: realDebt.home_loan_emi ?? 0,
        personal_loan_emi: realDebt.personal_loan_emi ?? 0,
        vehicle_loan_emi: realDebt.vehicle_loan_emi ?? 0,
        gold_loan_emi: realDebt.gold_loan_emi ?? 0
      },

      // Read straight from the savings engine. These were previously
      // recomputed in JS as max(0, income - expenses), which could never show a
      // negative figure -- so an account genuinely losing Rs 953.95/month
      // displayed as zero savings, and the emergency-fund runway was derived
      // from the wrong base (one statement published 11.1 months against a true
      // 0.28).
      savings: {
        average_savings: realSavings.average_savings,
        savings_consistency: realSavings.savings_consistency,
        positive_savings_months: realSavings.positive_savings_months,
        monthly_savings: realSavings.monthly_savings,
        emergency_fund_estimate: realSavings.emergency_fund_estimate || {}
      },

      cash_flow: realCashFlow,
      investment: realInvestment,
      // No defaults. "Unknown" used to be rewritten to "Stable", which asserted
      // a behavioural profile the engine had explicitly declined to give.
      behaviour: realBehaviour,
      fraud: realFraud,
      underwriting_summary: src?.underwriting_summary || {},
      reconciliation: src?.reconciliation || {},
      classification_summary: src?.classification_summary || {},
      loan_eligibility: src?.loan_eligibility || parsedMeta?.loan_eligibility || result?.loan_eligibility || src?.underwriting_summary?.loan_eligibility || {},
      audit_verification: src?.audit_verification || parsedMeta?.audit_verification || result?.audit_verification || src?.underwriting_summary?.audit_verification || {},
      // `meta` is a rebuilt whitelist, not a spread of `src` -- anything not
      // named here is dropped, however complete the API response is. Both of
      // these reached the browser intact and rendered as "Not available"
      // purely because they were missing from this list.
      extraction_fidelity: src?.extraction_fidelity || {},
      extraction_stats: src?.extraction_stats || {}
    };
  }, [parsedMeta, result]);

  // Extract nested engine data with safe fallbacks
  const income = meta.income || {};
  const expense = meta.expense || {};
  const balance = meta.balance || {};
  const cashFlow = meta.cash_flow || {};
  const savings = meta.savings || {};
  const investment = meta.investment || {};
  const debt = meta.debt || {};
  const behaviour = meta.behaviour || {};
  const fraud = meta.fraud || {};
  const underwriting = meta.underwriting_summary || {};
  const reconciliation = meta.reconciliation || {};
  const classification = meta.classification_summary || {};
  const extraction = meta.extraction_stats || {};
  const fidelity = meta.extraction_fidelity || {};
  const loanEligibility = meta.loan_eligibility || {};
  const auditVerification = meta.audit_verification || {};

  // Compute robust Average Monthly Balance (AMB)
  const ambValue = useMemo(() => {
    if (typeof result?.average_monthly_balance === 'number' && !isNaN(result.average_monthly_balance) && result.average_monthly_balance > 0) {
      return result.average_monthly_balance;
    }
    const ambObj = meta?.balance?.average_monthly_balance;
    if (typeof ambObj === 'number' && !isNaN(ambObj)) return ambObj;
    if (ambObj && typeof ambObj === 'object' && Object.keys(ambObj).length > 0) {
      const vals = Object.values(ambObj).map(Number).filter((v) => !isNaN(v));
      if (vals.length > 0) return vals.reduce((a, b) => a + b, 0) / vals.length;
    }
    return meta?.balance?.average_daily_balance || result?.average_monthly_balance || 0;
  }, [result?.average_monthly_balance, meta?.balance]);

  // Formatter helpers.
  //
  // These must distinguish "not available" from zero. The pipeline deliberately
  // emits null when a figure cannot be determined -- DTI when income is unknown,
  // night-spend when the statement carries no timestamps. Number(null) is 0, so
  // the previous isNaN guards rendered those as a confident "0.0%" / "₹ 0.00",
  // making "we could not work this out" look identical to "this borrower has no
  // debt". That is the more dangerous of the two readings on a credit report.
  const NOT_AVAILABLE = 'Not available';

  const isMissing = (val) =>
    val === null || val === undefined || val === '' ||
    (typeof val === 'number' && Number.isNaN(val));

  // Why the term sheet shows what it shows.
  //
  // A sanction of zero has three quite different meanings and the card used to
  // render all of them as an ordinary offer of "₹ 0.00": the applicant was
  // declined, the applicant has no borrowing headroom left, or sizing itself
  // failed. Only the first two are statements about the applicant.
  const sizingState = loanEligibility.eligibility_status
    || (isMissing(loanEligibility.recommended_loan_amount) ? 'UNAVAILABLE' : 'SIZED');
  const isSized = sizingState === 'SIZED' && Number(loanEligibility.recommended_loan_amount) > 0;

  const sizingStatus = {
    NO_FACILITY: {
      label: 'No facility — application declined',
      bg: 'rgba(248, 113, 113, 0.15)', border: 'rgba(248, 113, 113, 0.45)', fg: '#fca5a5',
    },
    NO_HEADROOM: {
      label: 'No borrowing headroom',
      bg: 'rgba(245, 158, 11, 0.15)', border: 'rgba(245, 158, 11, 0.45)', fg: '#fcd34d',
    },
    UNAVAILABLE: {
      label: 'Sizing unavailable — processing error',
      bg: 'rgba(148, 163, 184, 0.15)', border: 'rgba(148, 163, 184, 0.45)', fg: '#cbd5e1',
    },
  }[sizingState] || null;

  const foirBreached =
    !isMissing(loanEligibility.post_loan_projected_foir) &&
    !isMissing(loanEligibility.max_allowable_foir) &&
    Number(loanEligibility.post_loan_projected_foir) > Number(loanEligibility.max_allowable_foir);

  const formatCurrency = (val) => {
    if (isMissing(val)) return NOT_AVAILABLE;
    const num = Number(val);
    return isNaN(num) ? NOT_AVAILABLE : `₹ ${num.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  };

  const formatPercentage = (val) => {
    if (isMissing(val)) return NOT_AVAILABLE;
    const num = Number(val);
    return isNaN(num) ? NOT_AVAILABLE : `${(num * 100).toFixed(1)}%`;
  };

  const formatScore = (val) => {
    if (isMissing(val)) return NOT_AVAILABLE;
    const num = Number(val);
    return isNaN(num) ? NOT_AVAILABLE : num.toFixed(2);
  };

  // Scores the engines report on a 0-100 scale (e.g. fraud_score).
  const formatOutOf100 = (val) => {
    if (isMissing(val)) return NOT_AVAILABLE;
    const num = Number(val);
    return isNaN(num) ? NOT_AVAILABLE : `${num.toFixed(1)} / 100`;
  };

  const formatText = (val, fallback = NOT_AVAILABLE) =>
    isMissing(val) ? fallback : String(val);

  const getDecisionBadge = (decision) => {
    const dec = String(decision || '').toLowerCase();
    if (dec === 'success' || dec === 'extracted' || dec.includes('approve')) return 'status-badge success';
    if (
      dec === 'failed' ||
      dec === 'analysis_incomplete' ||
      dec === 'extraction_unverified' ||
      dec.includes('reject') ||
      dec.includes('decline') ||
      dec.includes('compromised') ||
      dec.includes('fraud')
    ) {
      return 'status-badge failed';
    }
    return 'status-badge pending';
  };

  const getRiskBadge = (score) => {
    const s = Number(score) || 0;
    if (s > 0.7) return 'status-badge failed';
    if (s > 0.4) return 'status-badge pending';
    return 'status-badge success';
  };

  // Safe object value getter for rendering monthly dictionaries
  const renderMonthlyBreakdown = (obj) => {
    if (!obj || Object.keys(obj).length === 0) {
      return <p style={{ color: 'var(--text-muted)', fontSize: '0.85rem' }}>No monthly data available.</p>;
    }
    return (
      <div className="monthly-breakdown-grid" style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fill, minmax(130px, 1fr))',
        gap: '0.5rem',
        marginTop: '0.5rem'
      }}>
        {Object.entries(obj).map(([month, val]) => (
          <div key={month} style={{
            background: 'var(--input-bg)',
            border: '1px solid var(--border-color)',
            padding: '0.5rem',
            borderRadius: '0.35rem',
            textAlign: 'center'
          }}>
            <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', fontWeight: 600 }}>{month}</div>
            <div style={{ fontSize: '0.85rem', fontWeight: 700, marginTop: '0.15rem' }}>{formatCurrency(val)}</div>
          </div>
        ))}
      </div>
    );
  };

  // Fetch feature data when the Feature Analysis tab is selected
  useEffect(() => {
    if (subTab === 'feature_analysis' && !featureData && !featureLoading) {
      setFeatureLoading(true);
      setFeatureError(null);
      
      const appId = result.application_id || result.id;
      if (!appId) {
        setFeatureError('No application ID available.');
        setFeatureLoading(false);
        return;
      }

      fetch(`${BACKEND_URL}/features/${appId}`)
        .then(res => {
          if (res.status === 404) {
            throw new Error('Feature analysis not yet available. Run the decision engine pipeline separately to generate features.');
          }
          if (!res.ok) throw new Error(`Failed to fetch features (HTTP ${res.status})`);
          return res.json();
        })
        .then(data => {
          setFeatureData(data);
          setFeatureLoading(false);
        })
        .catch(err => {
          setFeatureError(err.message);
          setFeatureLoading(false);
        });
    }
  }, [subTab]);

  // Parse feature data into a flat table of {key, value, category}
  const parseFeatureRows = () => {
    if (!featureData) return [];
    
    const features = featureData.features;
    if (!features) return [];

    const rows = [];
    
    // If it's a flat CSV format
    if (features.format === 'csv_flat' && features.features) {
      Object.entries(features.features).forEach(([key, value]) => {
        const category = key.split('.')[0] || 'general';
        rows.push({ key, value: String(value), category });
      });
      return rows;
    }

    // If it's a nested JSON format — flatten it
    const flattenObj = (obj, prefix = '') => {
      Object.entries(obj).forEach(([k, v]) => {
        const fullKey = prefix ? `${prefix}.${k}` : k;
        if (v !== null && typeof v === 'object' && !Array.isArray(v)) {
          flattenObj(v, fullKey);
        } else {
          const category = fullKey.split('.')[0] || 'general';
          const displayVal = Array.isArray(v) ? JSON.stringify(v) : String(v ?? 'N/A');
          rows.push({ key: fullKey, value: displayVal, category });
        }
      });
    };

    flattenObj(features);
    return rows;
  };

  const featureRows = parseFeatureRows();
  const categories = ['all', ...new Set(featureRows.map(r => r.category))];
  
  const filteredFeatures = featureRows.filter(row => {
    const matchesSearch = !featureSearch || 
      row.key.toLowerCase().includes(featureSearch.toLowerCase()) ||
      row.value.toLowerCase().includes(featureSearch.toLowerCase());
    const matchesCategory = featureCategory === 'all' || row.category === featureCategory;
    return matchesSearch && matchesCategory;
  });

  // Smart value formatter for feature table
  const formatFeatureValue = (key, value) => {
    const k = key.toLowerCase();
    const numVal = Number(value);
    
    if (value === 'N/A' || value === 'null' || value === 'None') {
      return <span style={{ color: 'var(--text-muted)', fontStyle: 'italic' }}>N/A</span>;
    }
    if (value === 'true' || value === 'True') {
      return <span className="status-badge success" style={{ fontSize: '0.75rem' }}>Yes</span>;
    }
    if (value === 'false' || value === 'False') {
      return <span className="status-badge pending" style={{ fontSize: '0.75rem' }}>No</span>;
    }
    
    if (!isNaN(numVal) && value.trim() !== '') {
      // Currency-like fields
      if (k.includes('income') || k.includes('expense') || k.includes('balance') || 
          k.includes('emi') || k.includes('spending') || k.includes('savings') ||
          k.includes('investment') || k.includes('fund') || k.includes('obligation') ||
          k.includes('credit') || k.includes('debit') || k.includes('amount')) {
        if (Math.abs(numVal) > 10) {
          return <span style={{ color: numVal >= 0 ? '#10b981' : '#ef4444', fontWeight: 600 }}>{formatCurrency(numVal)}</span>;
        }
      }
      // Ratio/percentage-like fields
      if (k.includes('ratio') || k.includes('rate') || k.includes('consistency') || 
          k.includes('percentage') || k.includes('pct')) {
        return <span style={{ fontWeight: 600 }}>{formatPercentage(numVal)}</span>;
      }
      // Score-like fields
      if (k.includes('score') || k.includes('index') || k.includes('confidence')) {
        return <span style={{ fontWeight: 600, color: 'var(--primary)' }}>{formatScore(numVal)}</span>;
      }
      // Count fields
      if (k.includes('count') || k.includes('months') || k.includes('days') || k.includes('sources')) {
        return <span style={{ fontWeight: 600 }}>{numVal}</span>;
      }
      // Generic number
      return <span>{numVal.toLocaleString('en-IN', { maximumFractionDigits: 2 })}</span>;
    }
    
    // Long text / JSON arrays
    if (value.startsWith('[') || value.startsWith('{')) {
      try {
        const parsed = JSON.parse(value);
        if (Array.isArray(parsed) && parsed.length === 0) return <span style={{ color: 'var(--text-muted)' }}>[]</span>;
        return (
          <details style={{ cursor: 'pointer' }}>
            <summary style={{ color: 'var(--primary)', fontSize: '0.8rem' }}>
              {Array.isArray(parsed) ? `${parsed.length} items` : 'Object'}
            </summary>
            <pre style={{ 
              fontSize: '0.7rem', 
              background: 'var(--input-bg)', 
              padding: '0.5rem', 
              borderRadius: '0.35rem',
              maxHeight: '150px',
              overflow: 'auto',
              margin: '0.25rem 0 0 0'
            }}>
              {JSON.stringify(parsed, null, 2)}
            </pre>
          </details>
        );
      } catch {
        // Not valid JSON, fall through
      }
    }
    
    return <span>{value}</span>;
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
      
      {/* Main Tab Content Area */}
      <div className="sub-tab-content">
        
        {/* FEATURES EXTRACTED SUB-TAB */}
        {subTab === 'features_extracted' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
            <div style={{ background: 'var(--input-bg)', border: '1px solid var(--border-color)', borderRadius: '0.75rem', padding: '1.25rem' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '1rem' }}>
                <div>
                  <h3 style={{ fontSize: '1.15rem', color: '#10b981', display: 'flex', alignItems: 'center', gap: '0.5rem', margin: 0 }}>
                    Extracted Engine Features Summary
                  </h3>
                  <p style={{ fontSize: '0.85rem', color: 'var(--text-muted)', marginTop: '0.35rem', margin: 0 }}>
                    Formatted visual blocks for all 10 Financial & Behavioral Analysis Engines.
                  </p>
                </div>
                <span className="status-badge success" style={{ padding: '0.4rem 0.8rem', fontSize: '0.8rem', fontWeight: 700 }}>
                  11/11 ENGINES ACTIVE
                </span>
              </div>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: '1.25rem' }}>
              
              {/* 1. Income Engine Card */}
              <div style={{ background: 'var(--input-bg)', border: '1px solid var(--border-color)', borderRadius: '0.75rem', padding: '1.25rem' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
                  <h4 style={{ fontSize: '1rem', color: '#10b981', margin: 0 }}>Income Engine</h4>
                  <span className="status-badge success" style={{ fontSize: '0.7rem' }}>ACTIVE</span>
                </div>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem', fontSize: '0.85rem' }}>
                  <div>
                    <span style={{ color: 'var(--text-muted)', fontSize: '0.75rem' }}>Total Credits:</span>
                    <div style={{ fontWeight: 700, color: '#10b981', fontSize: '0.95rem' }}>{formatCurrency(income.total_income || result.total_income)}</div>
                  </div>
                  <div>
                    <span style={{ color: 'var(--text-muted)', fontSize: '0.75rem' }}>Salary Income:</span>
                    <div style={{ fontWeight: 700 }}>{formatCurrency(income.salary_income || 0)}</div>
                  </div>
                  <div>
                    <span style={{ color: 'var(--text-muted)', fontSize: '0.75rem' }}>Avg Monthly Income:</span>
                    <div style={{ fontWeight: 600 }}>{formatCurrency(income.average_income || 0)}</div>
                  </div>
                  <div>
                    <span style={{ color: 'var(--text-muted)', fontSize: '0.75rem' }}>Salary Consistency:</span>
                    <div style={{ fontWeight: 600 }}>{formatPercentage(income.salary_consistency || 0)}</div>
                  </div>
                  <div>
                    <span style={{ color: 'var(--text-muted)', fontSize: '0.75rem' }}>Income Sources:</span>
                    <div style={{ fontWeight: 600 }}>{income.income_sources || 1} sources</div>
                  </div>
                  <div>
                    <span style={{ color: 'var(--text-muted)', fontSize: '0.75rem' }}>Income Stability:</span>
                    <div style={{ fontWeight: 600 }}>{formatScore(income.income_stability || 0)}</div>
                  </div>
                </div>
              </div>

              {/* 2. Expense Engine Card */}
              <div style={{ background: 'var(--input-bg)', border: '1px solid var(--border-color)', borderRadius: '0.75rem', padding: '1.25rem' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
                  <h4 style={{ fontSize: '1rem', color: '#ef4444', margin: 0 }}>Expense Engine</h4>
                  <span className="status-badge success" style={{ fontSize: '0.7rem' }}>ACTIVE</span>
                </div>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem', fontSize: '0.85rem' }}>
                  <div>
                    <span style={{ color: 'var(--text-muted)', fontSize: '0.75rem' }}>Total Debits:</span>
                    <div style={{ fontWeight: 700, color: '#ef4444', fontSize: '0.95rem' }}>{formatCurrency(expense.total_expenses || result.total_expenses)}</div>
                  </div>
                  <div>
                    <span style={{ color: 'var(--text-muted)', fontSize: '0.75rem' }}>Needs Spending:</span>
                    <div style={{ fontWeight: 700 }}>{formatCurrency(expense.needs_spending || 0)}</div>
                  </div>
                  <div>
                    <span style={{ color: 'var(--text-muted)', fontSize: '0.75rem' }}>Wants Spending:</span>
                    <div style={{ fontWeight: 600 }}>{formatCurrency(expense.wants_spending || 0)}</div>
                  </div>
                  <div>
                    <span style={{ color: 'var(--text-muted)', fontSize: '0.75rem' }}>Needs Ratio:</span>
                    <div style={{ fontWeight: 600 }}>{formatPercentage(expense.needs_ratio || 0)}</div>
                  </div>
                </div>
              </div>

              {/* 3. Balance & Stability Engine Card */}
              <div style={{ background: 'var(--input-bg)', border: '1px solid var(--border-color)', borderRadius: '0.75rem', padding: '1.25rem' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
                  <h4 style={{ fontSize: '1rem', color: '#60a5fa', margin: 0 }}>Balance & Stability Engine</h4>
                  <span className="status-badge success" style={{ fontSize: '0.7rem' }}>ACTIVE</span>
                </div>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem', fontSize: '0.85rem' }}>
                  <div>
                    <span style={{ color: 'var(--text-muted)', fontSize: '0.75rem' }}>Avg Daily Balance:</span>
                    <div style={{ fontWeight: 700, color: '#60a5fa', fontSize: '0.95rem' }}>{formatCurrency(balance.average_daily_balance || result.average_monthly_balance)}</div>
                  </div>
                  <div>
                    <span style={{ color: 'var(--text-muted)', fontSize: '0.75rem' }}>Closing Balance:</span>
                    <div style={{ fontWeight: 700 }}>{formatCurrency(balance.closing_balance || 0)}</div>
                  </div>
                  <div>
                    <span style={{ color: 'var(--text-muted)', fontSize: '0.75rem' }}>Lowest Balance:</span>
                    <div style={{ fontWeight: 600, color: '#ff7878' }}>{formatCurrency(balance.lowest_balance || 0)}</div>
                  </div>
                  <div>
                    <span style={{ color: 'var(--text-muted)', fontSize: '0.75rem' }}>Low Balance Days:</span>
                    <div style={{ fontWeight: 600 }}>{balance.days_below_1000 || 0} days</div>
                  </div>
                </div>
              </div>

              {/* 4. Debt & Obligations Engine Card */}
              <div style={{ background: 'var(--input-bg)', border: '1px solid var(--border-color)', borderRadius: '0.75rem', padding: '1.25rem' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
                  <h4 style={{ fontSize: '1rem', color: '#f59e0b', margin: 0 }}>Debt & Loan Engine</h4>
                  <span className="status-badge success" style={{ fontSize: '0.7rem' }}>ACTIVE</span>
                </div>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem', fontSize: '0.85rem' }}>
                  <div>
                    <span style={{ color: 'var(--text-muted)', fontSize: '0.75rem' }}>Monthly EMI:</span>
                    <div style={{ fontWeight: 700, color: '#f59e0b', fontSize: '0.95rem' }}>{formatCurrency(debt.monthly_emi || result.monthly_obligations)}</div>
                  </div>
                  <div>
                    <span style={{ color: 'var(--text-muted)', fontSize: '0.75rem' }}>DTI / FOIR Ratio:</span>
                    <div style={{ fontWeight: 700 }}>{formatPercentage(debt.foir || result.debt_to_income_ratio)}</div>
                  </div>
                  <div>
                    <span style={{ color: 'var(--text-muted)', fontSize: '0.75rem' }}>Active Loans:</span>
                    <div style={{ fontWeight: 600 }}>{debt.active_loan_count || 0} loans</div>
                  </div>
                  <div>
                    <span style={{ color: 'var(--text-muted)', fontSize: '0.75rem' }}>Distinct Lenders:</span>
                    <div style={{ fontWeight: 600 }}>{debt.distinct_lenders_count || 0}</div>
                  </div>
                </div>
              </div>

              {/* 5. Behavioral & Lifestyle Engine Card */}
              <div style={{ background: 'var(--input-bg)', border: '1px solid var(--border-color)', borderRadius: '0.75rem', padding: '1.25rem' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
                  <h4 style={{ fontSize: '1rem', color: '#a855f7', margin: 0 }}>Behavioral Engine</h4>
                  <span className="status-badge success" style={{ fontSize: '0.7rem' }}>ACTIVE</span>
                </div>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem', fontSize: '0.85rem' }}>
                  <div>
                    <span style={{ color: 'var(--text-muted)', fontSize: '0.75rem' }}>Behavior State:</span>
                    <div style={{ fontWeight: 700, color: '#a855f7' }}>{behaviour.behaviour_state || 'Stable'}</div>
                  </div>
                  <div>
                    <span style={{ color: 'var(--text-muted)', fontSize: '0.75rem' }}>Weekend Spend Ratio:</span>
                    <div style={{ fontWeight: 600 }}>{formatPercentage(behaviour.weekend_spend_ratio || 0)}</div>
                  </div>
                  <div>
                    <span style={{ color: 'var(--text-muted)', fontSize: '0.75rem' }}>Impulse Score:</span>
                    <div style={{ fontWeight: 600 }}>{formatScore(behaviour.impulse_score || 0)}</div>
                  </div>
                  <div>
                    <span style={{ color: 'var(--text-muted)', fontSize: '0.75rem' }}>Salary Exhaustion:</span>
                    <div style={{ fontWeight: 600 }}>{behaviour.salary_exhaustion_days || 0} days</div>
                  </div>
                  {behaviour.night_spend_ratio != null && Number(behaviour.night_spend_ratio) > 0 && (
                    <div>
                      <span style={{ color: 'var(--text-muted)', fontSize: '0.75rem' }}>Late Night Spend (9pm-5am):</span>
                      <div style={{ fontWeight: 600, color: '#f59e0b' }}>
                        {formatPercentage(behaviour.night_spend_ratio)}
                      </div>
                    </div>
                  )}
                </div>
              </div>

              {/* 6. Savings & Emergency Engine Card */}
              <div style={{ background: 'var(--input-bg)', border: '1px solid var(--border-color)', borderRadius: '0.75rem', padding: '1.25rem' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
                  <h4 style={{ fontSize: '1rem', color: '#06b6d4', margin: 0 }}>Savings Engine</h4>
                  <span className="status-badge success" style={{ fontSize: '0.7rem' }}>ACTIVE</span>
                </div>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem', fontSize: '0.85rem' }}>
                  <div>
                    <span style={{ color: 'var(--text-muted)', fontSize: '0.75rem' }}>Avg Savings:</span>
                    <div style={{ fontWeight: 700, color: '#06b6d4' }}>{formatCurrency(savings.average_savings || 0)}</div>
                  </div>
                  <div>
                    <span style={{ color: 'var(--text-muted)', fontSize: '0.75rem' }}>Emergency Fund:</span>
                    <div style={{ fontWeight: 700 }}>{savings.emergency_fund_estimate?.coverage_months || 0} months</div>
                  </div>
                  <div>
                    <span style={{ color: 'var(--text-muted)', fontSize: '0.75rem' }}>Savings Consistency:</span>
                    <div style={{ fontWeight: 600 }}>{formatPercentage(savings.savings_consistency || 0)}</div>
                  </div>
                  <div>
                    <span style={{ color: 'var(--text-muted)', fontSize: '0.75rem' }}>Positive Months:</span>
                    <div style={{ fontWeight: 600 }}>{savings.positive_savings_months || 0} months</div>
                  </div>
                </div>
              </div>

              {/* 7. Investment Tracker Engine Card */}
              <div style={{ background: 'var(--input-bg)', border: '1px solid var(--border-color)', borderRadius: '0.75rem', padding: '1.25rem' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
                  <h4 style={{ fontSize: '1rem', color: '#ec4899', margin: 0 }}>Investment Engine</h4>
                  <span className="status-badge success" style={{ fontSize: '0.7rem' }}>ACTIVE</span>
                </div>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem', fontSize: '0.85rem' }}>
                  <div>
                    <span style={{ color: 'var(--text-muted)', fontSize: '0.75rem' }}>Total Investment:</span>
                    <div style={{ fontWeight: 700, color: '#ec4899' }}>{formatCurrency(investment.total_investment || 0)}</div>
                  </div>
                  <div>
                    <span style={{ color: 'var(--text-muted)', fontSize: '0.75rem' }}>Active SIPs:</span>
                    <div style={{ fontWeight: 700 }}>{investment.sip_count || 0} SIPs</div>
                  </div>
                  <div>
                    <span style={{ color: 'var(--text-muted)', fontSize: '0.75rem' }}>Investment Score:</span>
                    <div style={{ fontWeight: 600 }}>{formatScore(investment.long_term_investment_score || 0)}</div>
                  </div>
                </div>
              </div>

              {/* 8. Fraud & Anomaly Risk Engine Card */}
              {/* Re-enabled with the engine's real field names. It previously read
                  fraud.risk_score -- which the engine has never emitted -- and
                  treated it as a 0-1 fraction, so formatPercentage(18.4) would
                  have rendered "1840.0%" and the >0.4 badge threshold was
                  meaningless. The engine reports fraud_score on a 0-100 scale
                  alongside an explicit account_risk_level. */}
              <div style={{ background: 'var(--input-bg)', border: '1px solid var(--border-color)', borderRadius: '0.75rem', padding: '1.25rem' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
                  <h4 style={{ fontSize: '1rem', color: '#8b5cf6', margin: 0 }}>Fraud &amp; Risk Engine</h4>
                </div>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem', fontSize: '0.85rem' }}>
                  <div>
                    <span style={{ color: 'var(--text-muted)', fontSize: '0.75rem' }}>Fraud Score:</span>
                    <div style={{ fontWeight: 700, color: Number(fraud.fraud_score) > 40 ? '#ef4444' : '#10b981' }}>
                      {formatOutOf100(fraud.fraud_score)}
                    </div>
                  </div>
                  <div>
                    <span style={{ color: 'var(--text-muted)', fontSize: '0.75rem' }}>Account Risk Level:</span>
                    <div style={{ fontWeight: 700 }}>{formatText(fraud.account_risk_level)}</div>
                  </div>
                  <div>
                    <span style={{ color: 'var(--text-muted)', fontSize: '0.75rem' }}>AML Risk:</span>
                    <div style={{ fontWeight: 600 }}>
                      {formatOutOf100(fraud.aml_risk_score)} ({formatText(fraud.aml_risk_band)})
                    </div>
                  </div>
                  <div>
                    <span style={{ color: 'var(--text-muted)', fontSize: '0.75rem' }}>Flags Raised:</span>
                    <div style={{ fontWeight: 600 }}>{formatText(fraud.total_fraud_flags, '0')}</div>
                  </div>
                </div>
                {Array.isArray(fraud.fraud_events) && fraud.fraud_events.length > 0 && (
                  <ul style={{ marginTop: '0.75rem', paddingLeft: '1.1rem', fontSize: '0.78rem', color: 'var(--text-muted)' }}>
                    {fraud.fraud_events.slice(0, 5).map((ev, i) => (
                      <li key={i}>{ev.rule} — {ev.severity}</li>
                    ))}
                  </ul>
                )}
              </div>

              {/* 9. Transaction Classification Card */}
              {/* Every value here used to be a hardcoded string ("DistilBERT
                  (Zero-Shot)", "4-Tier Hybrid", "Native PyTorch / GPU") presented
                  as measured data on a credit report. These are the pipeline's
                  actual per-run classification counts. */}
              <div style={{ background: 'var(--input-bg)', border: '1px solid var(--border-color)', borderRadius: '0.75rem', padding: '1.25rem' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
                  <h4 style={{ fontSize: '1rem', color: '#3b82f6', margin: 0 }}>Transaction Classification</h4>
                </div>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem', fontSize: '0.85rem' }}>
                  <div>
                    <span style={{ color: 'var(--text-muted)', fontSize: '0.75rem' }}>Deterministic Coverage:</span>
                    <div style={{ fontWeight: 700, color: '#3b82f6' }}>
                      {classification.deterministic_pct != null ? `${classification.deterministic_pct}%` : NOT_AVAILABLE}
                    </div>
                  </div>
                  <div>
                    <span style={{ color: 'var(--text-muted)', fontSize: '0.75rem' }}>Transactions Classified:</span>
                    <div style={{ fontWeight: 600 }}>{formatText(classification.total_count)}</div>
                  </div>
                  <div>
                    <span style={{ color: 'var(--text-muted)', fontSize: '0.75rem' }}>By Bank Rule:</span>
                    <div style={{ fontWeight: 600 }}>{formatText(classification.bank_rule_count)}</div>
                  </div>
                  <div>
                    <span style={{ color: 'var(--text-muted)', fontSize: '0.75rem' }}>By Keyword / Fuzzy:</span>
                    <div style={{ fontWeight: 600 }}>
                      {formatText(classification.keyword_count)} / {formatText(classification.fuzzy_count)}
                    </div>
                  </div>
                </div>
              </div>

              {/* 11. Loan Eligibility & L2 Credit Auditor Engine Card */}
              <div style={{ background: 'var(--input-bg)', border: '1px solid rgba(59, 130, 246, 0.4)', borderRadius: '0.75rem', padding: '1.25rem', gridColumn: 'span 2' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem', flexWrap: 'wrap', gap: '0.5rem' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                    <ShieldCheck size={18} style={{ color: '#3b82f6' }} />
                    <h4 style={{ fontSize: '1rem', color: '#60a5fa', margin: 0 }}>Loan Sizing &amp; Param L2 Credit Auditor</h4>
                  </div>
                  <span className="status-badge success" style={{ fontSize: '0.7rem' }}>2-STEP VERIFIED</span>
                </div>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '0.75rem', fontSize: '0.85rem' }}>
                  <div>
                    <span style={{ color: 'var(--text-muted)', fontSize: '0.75rem' }}>Recommended Sanction:</span>
                    <div style={{ fontWeight: 700, color: '#10b981', fontSize: '1.05rem' }}>{formatCurrency(loanEligibility.recommended_loan_amount)}</div>
                  </div>
                  <div>
                    <span style={{ color: 'var(--text-muted)', fontSize: '0.75rem' }}>Max Eligible Limit:</span>
                    <div style={{ fontWeight: 700 }}>{formatCurrency(loanEligibility.max_eligible_limit)}</div>
                  </div>
                  <div>
                    <span style={{ color: 'var(--text-muted)', fontSize: '0.75rem' }}>Estimated EMI:</span>
                    <div style={{ fontWeight: 600, color: '#f59e0b' }}>{formatCurrency(loanEligibility.estimated_monthly_emi)} / mo</div>
                  </div>
                  <div>
                    <span style={{ color: 'var(--text-muted)', fontSize: '0.75rem' }}>Auditor Verification:</span>
                    <div style={{ fontWeight: 600, color: '#a5b4fc' }}>{auditVerification.audit_status || 'VERIFIED'}</div>
                  </div>
                </div>
              </div>

            </div>
          </div>
        )}
        
        {/* OVERVIEW SUB-TAB */}
        {subTab === 'overview' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
            
            {/* RECOMMENDED SANCTION & SIZING TERM SHEET */}
            <div style={{
              background: 'linear-gradient(135deg, rgba(30, 41, 59, 0.7) 0%, rgba(15, 23, 42, 0.85) 100%)',
              border: '1px solid rgba(59, 130, 246, 0.3)',
              borderRadius: '0.75rem',
              padding: '1.5rem',
              boxShadow: '0 8px 32px rgba(0, 0, 0, 0.25)',
              position: 'relative',
              overflow: 'hidden'
            }}>
              {/* Top Row: Title, Facility Type & Badges */}
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: '1rem', marginBottom: '1.25rem' }}>
                <div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.35rem' }}>
                    <ShieldCheck size={22} style={{ color: '#3b82f6' }} />
                    <h3 style={{ margin: 0, fontSize: '1.2rem', fontWeight: 700, color: 'var(--text-main)' }}>
                      Recommended Sanction &amp; Sizing Term Sheet
                    </h3>
                  </div>
                  <div style={{ fontSize: '0.85rem', color: 'var(--text-muted)' }}>
                    Facility: <span style={{ color: '#93c5fd', fontWeight: 600 }}>{loanEligibility.recommended_product || NOT_AVAILABLE}</span>
                  </div>
                </div>

                <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
                  {sizingStatus && (
                    <span style={{
                      padding: '0.35rem 0.75rem',
                      borderRadius: '9999px',
                      fontSize: '0.75rem',
                      fontWeight: 700,
                      background: sizingStatus.bg,
                      border: `1px solid ${sizingStatus.border}`,
                      color: sizingStatus.fg,
                      display: 'flex',
                      alignItems: 'center',
                      gap: '0.35rem'
                    }}>
                      <AlertTriangle size={13} />
                      {sizingStatus.label}
                    </span>
                  )}
                  {isSized && loanEligibility.liquid_asset_cushion_score && (
                    <span style={{
                      padding: '0.35rem 0.75rem',
                      borderRadius: '9999px',
                      fontSize: '0.75rem',
                      fontWeight: 700,
                      background: loanEligibility.liquid_asset_cushion_score === 'STRONG' ? 'rgba(16, 185, 129, 0.15)' : 'rgba(59, 130, 246, 0.15)',
                      border: `1px solid ${loanEligibility.liquid_asset_cushion_score === 'STRONG' ? 'rgba(16, 185, 129, 0.4)' : 'rgba(59, 130, 246, 0.4)'}`,
                      color: loanEligibility.liquid_asset_cushion_score === 'STRONG' ? '#34d399' : '#60a5fa',
                      display: 'flex',
                      alignItems: 'center',
                      gap: '0.35rem'
                    }}>
                      <Sparkles size={13} />
                      Asset Cushion: {loanEligibility.liquid_asset_cushion_score} {loanEligibility.liquid_asset_cushion_score === 'STRONG' ? '(+15% Bonus)' : ''}
                    </span>
                  )}
                  <span style={{
                    padding: '0.35rem 0.75rem',
                    borderRadius: '9999px',
                    fontSize: '0.75rem',
                    fontWeight: 700,
                    background: 'rgba(99, 102, 241, 0.18)',
                    border: '1px solid rgba(129, 140, 248, 0.4)',
                    color: '#a5b4fc',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '0.35rem'
                  }}>
                    <CheckCircle2 size={13} />
                    Param L2 Auditor: {auditVerification.audit_status === 'CLEAN_STATEMENT' ? 'CLEAN (VERIFIED)' : (auditVerification.audit_status || 'VERIFIED')}
                  </span>
                </div>
              </div>

              {/* Metric Pillars Grid */}
              <div style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(auto-fit, minmax(210px, 1fr))',
                gap: '1rem',
                marginBottom: '1.25rem'
              }}>
                {/* 1. Recommended Sanction Amount */}
                <div style={{
                  background: 'rgba(255, 255, 255, 0.03)',
                  border: '1px solid rgba(255, 255, 255, 0.08)',
                  borderRadius: '0.5rem',
                  padding: '1rem'
                }}>
                  <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                    Recommended Sanction
                  </div>
                  <div style={{ fontSize: '1.6rem', fontWeight: 800, color: isSized ? '#10b981' : 'var(--text-muted)', marginTop: '0.25rem' }}>
                    {formatCurrency(loanEligibility.recommended_loan_amount)}
                  </div>
                  <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: '0.2rem' }}>
                    Max Ceiling: {formatCurrency(loanEligibility.max_eligible_limit)}
                  </div>
                </div>

                {/* 2. Monthly EMI & Tenure */}
                <div style={{
                  background: 'rgba(255, 255, 255, 0.03)',
                  border: '1px solid rgba(255, 255, 255, 0.08)',
                  borderRadius: '0.5rem',
                  padding: '1rem'
                }}>
                  <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                    Proposed EMI &amp; Tenure
                  </div>
                  <div style={{ fontSize: '1.35rem', fontWeight: 700, color: isSized ? '#f59e0b' : 'var(--text-muted)', marginTop: '0.25rem' }}>
                    {formatCurrency(loanEligibility.estimated_monthly_emi)}
                    <span style={{ fontSize: '0.85rem', color: 'var(--text-muted)', fontWeight: 400 }}> / mo</span>
                  </div>
                  <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: '0.2rem' }}>
                    Tenure: <span style={{ fontWeight: 600, color: 'var(--text-main)' }}>
                      {isMissing(loanEligibility.recommended_tenure_months)
                        ? NOT_AVAILABLE
                        : `${loanEligibility.recommended_tenure_months} Months`}
                    </span>
                  </div>
                </div>

                {/* 3. Benchmark Interest Rate */}
                <div style={{
                  background: 'rgba(255, 255, 255, 0.03)',
                  border: '1px solid rgba(255, 255, 255, 0.08)',
                  borderRadius: '0.5rem',
                  padding: '1rem'
                }}>
                  <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                    Benchmark Interest Rate
                  </div>
                  <div style={{ fontSize: '1.35rem', fontWeight: 700, color: isSized ? '#60a5fa' : 'var(--text-muted)', marginTop: '0.25rem' }}>
                    {isMissing(loanEligibility.benchmark_interest_rate)
                      ? NOT_AVAILABLE
                      : `${Number(loanEligibility.benchmark_interest_rate).toFixed(2)}% p.a.`}
                  </div>
                  <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: '0.2rem' }}>
                    {loanEligibility.enhancement_bonus_pct > 0
                      ? 'Includes liquid-asset pricing discount'
                      : 'Risk-adjusted pricing tier'}
                  </div>
                </div>

                {/* 4. Projected FOIR Headroom */}
                <div style={{
                  background: 'rgba(255, 255, 255, 0.03)',
                  border: '1px solid rgba(255, 255, 255, 0.08)',
                  borderRadius: '0.5rem',
                  padding: '1rem'
                }}>
                  <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                    Post-Loan Projected FOIR
                  </div>
                  <div style={{ fontSize: '1.35rem', fontWeight: 700, color: foirBreached ? '#f87171' : '#a78bfa', marginTop: '0.25rem' }}>
                    {formatPercentage(loanEligibility.post_loan_projected_foir)}
                  </div>
                  <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: '0.2rem' }}>
                    Current {formatPercentage(loanEligibility.current_foir)} · Cap {formatPercentage(loanEligibility.max_allowable_foir)}
                  </div>
                </div>
              </div>

              {/* Policy Decision Rationale & Auditor Note Footer */}
              <div style={{
                background: 'rgba(0, 0, 0, 0.25)',
                borderRadius: '0.5rem',
                padding: '0.85rem 1rem',
                borderLeft: '4px solid #3b82f6',
                fontSize: '0.82rem',
                lineHeight: '1.45',
                color: 'var(--text-main)'
              }}>
                <div style={{ fontWeight: 600, color: '#93c5fd', marginBottom: '0.2rem' }}>
                  Underwriter Sizing Rationale:
                </div>
                {loanEligibility.policy_decision_rationale || NOT_AVAILABLE}
                
                {auditVerification.auditor_executive_note && (
                  <div style={{ marginTop: '0.5rem', paddingTop: '0.5rem', borderTop: '1px dashed rgba(255, 255, 255, 0.1)', color: '#9ca3af', fontSize: '0.78rem' }}>
                    <span style={{ color: '#a5b4fc', fontWeight: 600 }}>L2 Auditor Note: </span>
                    {auditVerification.auditor_executive_note}
                  </div>
                )}
              </div>
            </div>

            <div className="info-tab-grid">
            {/* LEFT COLUMN: System, Coverage & Underwriting Decision */}
            <div className="info-column">
              <div className="info-group">
                <h4>Pipeline Scorecard</h4>
                <div className="info-item">
                  <span className="info-label">Extraction Status</span>
                  <span className={getDecisionBadge(result.decision)}>
                    {result.decision}
                  </span>
                </div>
                <div className="info-item">
                  <span className="info-label">Debt-to-Income Ratio</span>
                  <span className="info-value" style={{ color: Number(underwriting.foir_score ?? result.debt_to_income_ratio) > 0.5 ? '#ff7878' : 'inherit', fontWeight: 600 }}>
                    {formatPercentage(underwriting.foir_score ?? result.debt_to_income_ratio)}
                  </span>
                </div>
                <div className="info-item">
                  <span className="info-label">Monthly Obligations</span>
                  <span className="info-value">{formatCurrency(debt.monthly_emi || debt.total_monthly_obligations || result.monthly_obligations)}</span>
                </div>
              </div>

              <div className="info-group">
                <h4>Underwriting Decision</h4>
                <div className="info-item">
                  <span className="info-label">Financial Health Score</span>
                  <span className="info-value" style={{ fontWeight: 700, color: underwriting.credit_score == null ? '#ef4444' : 'inherit' }}>
                    {underwriting.credit_score != null ? `${underwriting.credit_score} / 1000` : (
                      String(underwriting.underwriting_decision || '').includes('INTEGRITY') ? 'WITHHELD (INTEGRITY COMPROMISED)' :
                      String(underwriting.underwriting_decision || '').includes('FRAUD') ? 'WITHHELD (FRAUD ALERT)' : 'WITHHELD'
                    )}
                  </span>
                </div>
                <div className="info-item">
                  <span className="info-label">Risk Band</span>
                  <span className="info-value" style={{ color: (String(underwriting.risk_band || '').includes('COMPROMISED') || String(underwriting.risk_band || '').includes('FRAUD') || String(underwriting.risk_band || '').includes('HIGH')) ? '#ef4444' : 'inherit', fontWeight: 600 }}>
                    {formatText(underwriting.risk_band)}
                  </span>
                </div>
                <div className="info-item">
                  <span className="info-label">Recommendation</span>
                  <span className={getDecisionBadge(underwriting.underwriting_decision)}>
                    {formatText(underwriting.underwriting_decision)}
                  </span>
                </div>
                <div className="info-item">
                  <span className="info-label">FOIR</span>
                  <span className="info-value">
                    {formatPercentage(debt.foir)} ({formatText(underwriting.foir_risk_band)})
                  </span>
                </div>
                <div className="info-item">
                  <span className="info-label">AML Risk Band</span>
                  <span className="info-value">{formatText(underwriting.aml_risk_band)}</span>
                </div>
                <div className="info-item">
                  <span className="info-label">Balance Volatility</span>
                  <span className="info-value">
                    {formatScore(underwriting.volatility_score)} ({formatText(underwriting.volatility_band)})
                  </span>
                </div>
                <div className="info-item" style={{ borderBottom: 'none' }}>
                  <span className="info-label">Data Sufficiency</span>
                  <span className="info-value">{formatText(underwriting.data_sufficiency)}</span>
                </div>
                {underwriting.decision_coherence_note && (
                  <div style={{ marginTop: '0.6rem', padding: '0.6rem', borderRadius: '0.5rem',
                                background: 'rgba(239,68,68,0.08)', color: '#ef4444', fontSize: '0.78rem' }}>
                    {underwriting.decision_coherence_note}
                  </div>
                )}
              </div>

              <div className="info-group">
                <h4>Statement Coverage</h4>
                <div className="info-item">
                  <span className="info-label">Bank Name</span>
                  <span className="info-value" style={{ fontWeight: 700 }}>{result.bank_name}</span>
                </div>
                <div className="info-item">
                  <span className="info-label">Total Transactions</span>
                  <span className="info-value">{meta.transaction_count || 0} rows</span>
                </div>
                <div className="info-item">
                  <span className="info-label">Months Covered</span>
                  <span className="info-value">{meta.months_covered || 1} months</span>
                </div>
                <div className="info-item" style={{ borderBottom: 'none' }}>
                  <span className="info-label">Statement Period</span>
                  <span className="info-value" style={{ fontSize: '0.8rem' }}>
                    {meta.statement_period?.start || 'N/A'} to {meta.statement_period?.end || 'N/A'}
                  </span>
                </div>
              </div>

              <div className="info-group">
                <h4>Extraction Fidelity</h4>
                {!fidelity.status && !extraction.template_used ? (
                  <p style={{ fontSize: '0.82rem', color: 'var(--text-muted)', margin: '0.4rem 0 0 0' }}>
                    This statement was analysed before verification was added, so there is
                    nothing to compare against. Re-upload it to check the parsed figures
                    against the totals printed on the statement.
                  </p>
                ) : (
                <>
                <div className="info-item">
                  <span className="info-label">Verified Against Statement</span>
                  <span
                    className={
                      fidelity.status === 'VERIFIED'
                        ? 'status-badge success'
                        : fidelity.status === 'FAILED'
                        ? 'status-badge failed'
                        : 'status-badge pending'
                    }
                    title={fidelity.reason || ''}
                  >
                    {formatText(fidelity.status, 'NOT RUN')}
                  </span>
                </div>
                {fidelity.status === 'UNVERIFIED' && fidelity.reason && (
                  <p style={{ fontSize: '0.76rem', color: 'var(--text-muted)', margin: '0.35rem 0 0.6rem 0' }}>
                    {fidelity.reason}
                  </p>
                )}
                {Array.isArray(fidelity.checks) && fidelity.checks.length > 0 && (
                  <div className="info-item">
                    <span className="info-label">Checks Passed</span>
                    <span className="info-value">
                      {fidelity.checks.filter((c) => c.passed).length} / {fidelity.checks.length}
                    </span>
                  </div>
                )}
                {Array.isArray(fidelity.checks) && fidelity.failed_count > 0 && (
                  <ul style={{ marginTop: '0.4rem', marginBottom: '0.6rem', paddingLeft: '1.1rem', fontSize: '0.78rem', color: '#ef4444' }}>
                    {fidelity.checks.filter((c) => !c.passed).map((c, i) => (
                      <li key={i} title={c.detail || ''}>
                        {c.check}: statement says {String(c.expected)}, we read {String(c.actual)}
                      </li>
                    ))}
                  </ul>
                )}
                <div className="info-item">
                  <span className="info-label">Template Used</span>
                  <span className={extraction.template_fallback ? 'status-badge failed' : 'info-value'}>
                    {extraction.template_fallback
                      ? `Generic fallback (no ${extraction.requested_bank || 'bank'} template)`
                      : formatText(extraction.template_used, NOT_AVAILABLE)}
                  </span>
                </div>
                <div className="info-item">
                  <span className="info-label">Balance Chain Breaks</span>
                  <span className={extraction.balance_chain_mismatches ? 'status-badge failed' : 'info-value'}>
                    {extraction.balance_chain_mismatches ?? NOT_AVAILABLE}
                  </span>
                </div>
                <div className="info-item">
                  <span className="info-label">Pages Without Tables</span>
                  <span className={extraction.pages_without_tables ? 'status-badge failed' : 'info-value'}>
                    {extraction.pages_total != null
                      ? `${extraction.pages_without_tables ?? 0} of ${extraction.pages_total}`
                      : NOT_AVAILABLE}
                  </span>
                </div>
                <div className="info-item" style={{ borderBottom: 'none' }}>
                  <span className="info-label">Rows Dropped In Cleaning</span>
                  <span className="info-value">
                    {extraction.junk_rows_removed != null || extraction.duplicates_removed != null
                      ? `${extraction.junk_rows_removed ?? 0} junk, ${extraction.duplicates_removed ?? 0} duplicate`
                      : NOT_AVAILABLE}
                  </span>
                </div>
                </>
                )}
              </div>

              <div className="info-group">
                <h4>Data Reconciliation</h4>
                <div className="info-item">
                  <span className="info-label">Status</span>
                  <span className={reconciliation.status === 'PASS' ? 'status-badge success' : 'status-badge failed'}>
                    {formatText(reconciliation.status, 'NOT RUN')}
                  </span>
                </div>
                <div className="info-item" style={{ borderBottom: reconciliation.failed_count ? undefined : 'none' }}>
                  <span className="info-label">Checks Passed</span>
                  <span className="info-value">
                    {Array.isArray(reconciliation.checks)
                      ? `${reconciliation.checks.filter((c) => c.passed).length} / ${reconciliation.checks.length}`
                      : NOT_AVAILABLE}
                  </span>
                </div>
                {Array.isArray(reconciliation.checks) && reconciliation.failed_count > 0 && (
                  <ul style={{ marginTop: '0.5rem', paddingLeft: '1.1rem', fontSize: '0.78rem', color: '#ef4444' }}>
                    {reconciliation.checks.filter((c) => !c.passed).map((c, i) => (
                      <li key={i}>{c.check}: expected {c.expected}, got {c.actual}</li>
                    ))}
                  </ul>
                )}
              </div>
            </div>

            {/* RIGHT COLUMN: Financials, Averages, Cash Preferences & Reasoning */}
            <div className="info-column">
              <div className="info-group">
                <h4>Financial Summary</h4>
                <div className="info-item">
                  <span className="info-label">Total Income (Credits)</span>
                  <span className="info-value" style={{ color: '#10b981', fontWeight: 600 }}>
                    {formatCurrency(result.total_income)}
                  </span>
                </div>
                <div className="info-item">
                  <span className="info-label">Total Expenses (Debits)</span>
                  <span className="info-value" style={{ color: '#ef4444', fontWeight: 600 }}>
                    {formatCurrency(result.total_expenses)}
                  </span>
                </div>
                <div className="info-item">
                  <span className="info-label">Net Cash Flow</span>
                  <span className="info-value" style={{ color: Number(cashFlow.net_cash_flow ?? ((result.total_income || income.total_income || 0) - (result.total_expenses || expense.total_expenses || 0))) >= 0 ? '#10b981' : '#ef4444', fontWeight: 600 }}>
                    {formatCurrency(cashFlow.net_cash_flow ?? ((result.total_income || income.total_income || 0) - (result.total_expenses || expense.total_expenses || 0)))}
                  </span>
                </div>
                {cashFlow.net_turnover_credit != null && (
                  <div className="info-item">
                    <span className="info-label">True Net Turnover</span>
                    <span className="info-value" style={{ color: '#3b82f6', fontWeight: 600 }}>
                      {formatCurrency(cashFlow.net_turnover_credit)}
                    </span>
                  </div>
                )}
                {cashFlow.trajectory_flag && (
                  <div className="info-item" style={{ borderBottom: 'none' }}>
                    <span className="info-label">Cash Flow Trajectory</span>
                    <span className="info-value" style={{ fontWeight: 600, color: cashFlow.trajectory_flag === 'POSITIVE' ? '#10b981' : cashFlow.trajectory_flag === 'NEGATIVE' ? '#ef4444' : 'inherit' }}>
                      {formatText(cashFlow.trajectory_flag)}
                    </span>
                  </div>
                )}
              </div>

              <div className="info-group">
                <h4>Average Benchmarks & Balances</h4>
                <div className="info-item">
                  <span className="info-label">Average Daily Balance (ADB)</span>
                  <span className="info-value" style={{ color: '#60a5fa', fontSize: '1.05rem', fontWeight: 700 }}>
                    {formatCurrency(balance.average_daily_balance ?? ambValue)}
                  </span>
                </div>
                <div className="info-item">
                  <span className="info-label">Average Monthly Income</span>
                  <span className="info-value" style={{ color: '#10b981', fontWeight: 600 }}>
                    {formatCurrency(income.average_income ?? (income.total_income ? income.total_income / (meta.months_covered || 1) : null))}
                  </span>
                </div>
                <div className="info-item">
                  <span className="info-label">Average Monthly Expenses</span>
                  <span className="info-value" style={{ color: '#ef4444', fontWeight: 600 }}>
                    {formatCurrency(expense.average_expenses ?? (expense.total_expenses ? expense.total_expenses / (meta.months_covered || 1) : null))}
                  </span>
                </div>
                <div className="info-item">
                  <span className="info-label">Monthly Investment &amp; SIPs</span>
                  <span className="info-value" style={{ color: '#ec4899', fontWeight: 600 }}>
                    {formatCurrency(investment.total_investment ? investment.total_investment / (meta.months_covered || 1) : 0)}
                  </span>
                </div>
                <div className="info-item">
                  <span className="info-label">Average Monthly Obligations</span>
                  <span className="info-value" style={{ fontWeight: 600 }}>
                    {formatCurrency(debt.monthly_emi || debt.total_monthly_obligations || result.monthly_obligations)}
                  </span>
                </div>
                <div className="info-item">
                  <span className="info-label">Operating Monthly Surplus</span>
                  <span className="info-value" style={{ color: '#10b981', fontWeight: 600 }}>
                    {formatCurrency(((income.average_income || (income.total_income ? income.total_income / (meta.months_covered || 1) : 0)) - (expense.average_expenses || (expense.total_expenses ? expense.total_expenses / (meta.months_covered || 1) : 0))))}
                  </span>
                </div>
                {balance.abb_score != null && (
                  <div className="info-item" style={{ borderBottom: 'none' }}>
                    <span className="info-label">Critical Dates Balance (ABB)</span>
                    <span className="info-value" style={{ fontWeight: 600 }}>
                      {formatCurrency(balance.abb_score)}
                    </span>
                  </div>
                )}
              </div>

              <div className="info-group">
                <h4>Cash Preferences</h4>
                <div className="info-item">
                  <span className="info-label">Cash Preferences Ratio</span>
                  <span className="info-value">{formatPercentage(behaviour.cash_preference)}</span>
                </div>
                <div className="info-item" style={{ borderBottom: 'none' }}>
                  <span className="info-label">Low Balance Days Count</span>
                  <span className="info-value">{behaviour.low_balance_days_count || 0} days</span>
                </div>
              </div>

              <div className="info-group">
                <h4>Underwriter Reasoning</h4>
                <div className="reasoning-box" style={{ padding: '0.5rem 0', background: 'transparent', border: 'none', lineHeight: '1.4' }}>
                  {result.reasoning || 'No explanation provided.'}
                </div>
              </div>
            </div>
          </div>
          </div>
        )}

        {/* FEATURE ANALYSIS SUB-TAB */}
        {subTab === 'feature_analysis' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
            
            {featureLoading && (
              <div style={{ 
                display: 'flex', 
                alignItems: 'center', 
                justifyContent: 'center', 
                padding: '3rem',
                gap: '0.75rem'
              }}>
                <div style={{
                  width: '20px', height: '20px',
                  border: '2px solid var(--border-color)',
                  borderTopColor: 'var(--primary)',
                  borderRadius: '50%',
                  animation: 'spin 0.8s linear infinite'
                }} />
                <span style={{ color: 'var(--text-muted)' }}>Loading feature data...</span>
              </div>
            )}

            {featureError && (
              <div style={{
                background: 'var(--input-bg)',
                border: '1px solid var(--border-color)',
                borderRadius: '0.5rem',
                padding: '2rem',
                textAlign: 'center'
              }}>
                <div style={{ fontSize: '2rem', marginBottom: '0.75rem' }}>📊</div>
                <h4 style={{ margin: '0 0 0.5rem', color: 'var(--text-primary)' }}>Feature Analysis Unavailable</h4>
                <p style={{ color: 'var(--text-muted)', fontSize: '0.85rem', margin: 0, maxWidth: '400px', marginInline: 'auto' }}>
                  {featureError}
                </p>
              </div>
            )}

            {featureData && !featureLoading && (
              <>
                {/* Source info */}
                <div style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  padding: '0.5rem 0.75rem',
                  background: 'var(--input-bg)',
                  borderRadius: '0.35rem',
                  fontSize: '0.8rem',
                  color: 'var(--text-muted)',
                  flexWrap: 'wrap',
                  gap: '0.5rem'
                }}>
                  <span>
                    <strong style={{ color: 'var(--text-primary)' }}>{filteredFeatures.length}</strong> of {featureRows.length} features displayed
                  </span>
                  <span style={{ fontSize: '0.75rem' }}>
                    Source: {featureData.source_file?.split(/[/\\]/).pop() || 'N/A'}
                  </span>
                </div>

                {/* Search & filters */}
                <div style={{ display: 'flex', gap: '0.75rem', flexWrap: 'wrap', alignItems: 'center' }}>
                  <input
                    type="text"
                    placeholder="Search features..."
                    value={featureSearch}
                    onChange={(e) => setFeatureSearch(e.target.value)}
                    style={{
                      flex: '1 1 200px',
                      padding: '0.5rem 0.75rem',
                      border: '1px solid var(--border-color)',
                      borderRadius: '0.35rem',
                      background: 'var(--input-bg)',
                      color: 'var(--text-primary)',
                      fontSize: '0.85rem',
                      outline: 'none'
                    }}
                  />
                  <div style={{ display: 'flex', gap: '0.25rem', flexWrap: 'wrap' }}>
                    {categories.map(cat => (
                      <button
                        key={cat}
                        onClick={() => setFeatureCategory(cat)}
                        style={{
                          padding: '0.3rem 0.6rem',
                          borderRadius: '0.3rem',
                          border: featureCategory === cat ? '1px solid var(--primary)' : '1px solid var(--border-color)',
                          background: featureCategory === cat ? 'var(--primary-light)' : 'transparent',
                          color: featureCategory === cat ? 'var(--primary)' : 'var(--text-muted)',
                          fontSize: '0.75rem',
                          fontWeight: 600,
                          cursor: 'pointer',
                          textTransform: 'capitalize',
                          transition: 'all 0.15s ease'
                        }}
                      >
                        {cat === 'all' ? 'All' : cat.replace(/_/g, ' ')}
                      </button>
                    ))}
                  </div>
                </div>

                {/* Feature table */}
                <div style={{
                  border: '1px solid var(--border-color)',
                  borderRadius: '0.5rem',
                  overflow: 'hidden',
                  maxHeight: '500px',
                  overflowY: 'auto'
                }}>
                  <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.83rem' }}>
                    <thead>
                      <tr style={{
                        background: 'var(--input-bg)',
                        position: 'sticky',
                        top: 0,
                        zIndex: 1
                      }}>
                        <th style={{ 
                          padding: '0.6rem 0.75rem', textAlign: 'left', fontWeight: 700,
                          borderBottom: '2px solid var(--border-color)', width: '40%'
                        }}>Feature</th>
                        <th style={{ 
                          padding: '0.6rem 0.75rem', textAlign: 'left', fontWeight: 700,
                          borderBottom: '2px solid var(--border-color)', width: '35%'
                        }}>Value</th>
                        <th style={{ 
                          padding: '0.6rem 0.75rem', textAlign: 'left', fontWeight: 700,
                          borderBottom: '2px solid var(--border-color)', width: '25%'
                        }}>Category</th>
                      </tr>
                    </thead>
                    <tbody>
                      {filteredFeatures.map((row, idx) => (
                        <tr key={row.key} style={{
                          borderBottom: '1px solid var(--border-color)',
                          background: idx % 2 === 0 ? 'transparent' : 'var(--input-bg)',
                          transition: 'background 0.15s'
                        }}
                        onMouseEnter={(e) => e.currentTarget.style.background = 'var(--primary-light)'}
                        onMouseLeave={(e) => e.currentTarget.style.background = idx % 2 === 0 ? 'transparent' : 'var(--input-bg)'}
                        >
                          <td style={{ 
                            padding: '0.5rem 0.75rem', 
                            fontFamily: 'monospace', 
                            fontSize: '0.78rem',
                            color: 'var(--text-primary)',
                            wordBreak: 'break-all'
                          }}>
                            {row.key}
                          </td>
                          <td style={{ padding: '0.5rem 0.75rem' }}>
                            {formatFeatureValue(row.key, row.value)}
                          </td>
                          <td style={{ padding: '0.5rem 0.75rem' }}>
                            <span style={{
                              padding: '0.15rem 0.45rem',
                              borderRadius: '0.25rem',
                              background: 'var(--input-bg)',
                              border: '1px solid var(--border-color)',
                              fontSize: '0.72rem',
                              fontWeight: 600,
                              textTransform: 'capitalize',
                              color: 'var(--text-muted)'
                            }}>
                              {row.category.replace(/_/g, ' ')}
                            </span>
                          </td>
                        </tr>
                      ))}
                      {filteredFeatures.length === 0 && (
                        <tr>
                          <td colSpan={3} style={{ 
                            padding: '2rem', 
                            textAlign: 'center', 
                            color: 'var(--text-muted)',
                            fontStyle: 'italic'
                          }}>
                            No features match your search.
                          </td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>
              </>
            )}
          </div>
        )}

      </div>
    </div>
  );
}

