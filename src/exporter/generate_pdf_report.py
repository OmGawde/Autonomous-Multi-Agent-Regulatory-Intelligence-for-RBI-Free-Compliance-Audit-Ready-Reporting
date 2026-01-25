"""
PDF Report Generator - Converts JSON compliance report to formatted PDF
Generates audit-ready PDF with all 10 report sections
"""

import json
import logging
from pathlib import Path
from datetime import datetime
from reportlab.lib.pagesizes import letter, A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_JUSTIFY
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak, Table, TableStyle, Image
from reportlab.lib import colors

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class CompliancePDFGenerator:
    """Generate PDF reports from JSON compliance data"""
    
    def __init__(self, json_input_path, pdf_output_path):
        """
        Initialize PDF generator
        
        Args:
            json_input_path: Path to compliance_report.json
            pdf_output_path: Path where PDF should be saved
        """
        self.json_path = json_input_path
        self.pdf_path = pdf_output_path
        self.styles = getSampleStyleSheet()
        self._setup_custom_styles()
        self.report_data = None
        
    def _setup_custom_styles(self):
        """Setup custom paragraph styles for the report"""
        # Title style
        self.styles.add(ParagraphStyle(
            name='CustomTitle',
            parent=self.styles['Heading1'],
            fontSize=20,
            textColor=colors.HexColor('#1a3a52'),
            spaceAfter=12,
            alignment=TA_CENTER,
            fontName='Helvetica-Bold'
        ))
        
        # Heading 2 style
        self.styles.add(ParagraphStyle(
            name='CustomHeading2',
            parent=self.styles['Heading2'],
            fontSize=14,
            textColor=colors.HexColor('#2d5a7b'),
            spaceAfter=10,
            spaceBefore=10,
            fontName='Helvetica-Bold'
        ))
        
        # Section style
        self.styles.add(ParagraphStyle(
            name='SectionHeading',
            parent=self.styles['Heading3'],
            fontSize=12,
            textColor=colors.HexColor('#406a99'),
            spaceAfter=8,
            spaceBefore=8,
            fontName='Helvetica-Bold'
        ))
        
        # Body style
        self.styles.add(ParagraphStyle(
            name='CustomBody',
            parent=self.styles['BodyText'],
            fontSize=10,
            alignment=TA_JUSTIFY,
            spaceAfter=8,
            leading=12
        ))
        
        # Footer style
        self.styles.add(ParagraphStyle(
            name='FooterText',
            parent=self.styles['Normal'],
            fontSize=8,
            textColor=colors.grey,
            alignment=TA_CENTER
        ))
    
    def load_report_data(self):
        """Load compliance report from JSON file"""
        try:
            with open(self.json_path, 'r', encoding='utf-8') as f:
                self.report_data = json.load(f)
            logger.info(f"Loaded report data from: {self.json_path}")
            return True
        except FileNotFoundError:
            logger.error(f"Report file not found: {self.json_path}")
            return False
        except json.JSONDecodeError as e:
            logger.error(f"Error parsing JSON: {e}")
            return False
    
    def _build_report_header(self):
        """Build report header section"""
        elements = []
        header = self.report_data.get('report_header', {})
        
        # Title
        elements.append(Paragraph(header.get('report_title', 'RBI Compliance Report'), 
                                 self.styles['CustomTitle']))
        elements.append(Spacer(1, 0.2*inch))
        
        # Header info table
        header_data = [
            ['System Name:', header.get('system_name', 'N/A')],
            ['Compliance Domain:', header.get('compliance_domain', 'N/A')],
            ['Generated:', header.get('report_generated_on', 'N/A')],
            ['Reference No.:', header.get('rbi_circular_reference_no', 'N/A')],
        ]
        
        header_table = Table(header_data, colWidths=[2*inch, 4*inch])
        header_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#e8f0f7')),
            ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
            ('GRID', (0, 0), (-1, -1), 1, colors.grey),
        ]))
        elements.append(header_table)
        elements.append(Spacer(1, 0.3*inch))
        
        return elements
    
    def _build_executive_summary(self):
        """Build executive summary section"""
        elements = []
        summary = self.report_data.get('executive_summary', {})
        
        elements.append(Paragraph('Executive Summary', self.styles['CustomHeading2']))
        
        summary_data = [
            ['Overall Compliance Status:', summary.get('overall_compliance_status', 'N/A')],
            ['Total Obligations:', str(summary.get('total_obligations_extracted', 0))],
            ['Total Gaps Identified:', str(summary.get('total_gaps_identified', 0))],
            ['Processing Time:', f"{summary.get('processing_time_ms', 0)}ms"],
        ]
        
        summary_table = Table(summary_data, colWidths=[2.5*inch, 3.5*inch])
        summary_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#f5f5f5')),
            ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
            ('GRID', (0, 0), (-1, -1), 1, colors.lightgrey),
        ]))
        elements.append(summary_table)
        elements.append(Spacer(1, 0.3*inch))
        
        return elements
    
    def _build_rbi_circular_overview(self):
        """Build RBI circular overview section"""
        elements = []
        circular = self.report_data.get('rbi_circular_overview', {})
        
        elements.append(Paragraph('RBI Circular Overview', self.styles['CustomHeading2']))
        
        overview_data = [
            ['Circular Title:', circular.get('circular_title', 'N/A')],
            ['Official URL:', circular.get('official_url', 'N/A')],
            ['RSS Reference:', circular.get('rss_reference', 'N/A')],
            ['Effective Date:', circular.get('effective_date', 'N/A')],
            ['Applicability:', circular.get('applicability', 'N/A')],
        ]
        
        overview_table = Table(overview_data, colWidths=[2*inch, 4*inch])
        overview_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#f0f8ff')),
            ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
            ('ALIGN', (0, 0), (0, -1), 'LEFT'),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ('TOPPADDING', (0, 0), (-1, -1), 6),
            ('GRID', (0, 0), (-1, -1), 1, colors.lightgrey),
        ]))
        elements.append(overview_table)
        elements.append(Spacer(1, 0.3*inch))
        
        return elements
    
    def _build_compliance_obligations(self):
        """Build compliance obligations section"""
        elements = []
        obligations = self.report_data.get('extracted_compliance_obligations', [])
        
        elements.append(Paragraph('Extracted Compliance Obligations', self.styles['CustomHeading2']))
        
        if not obligations:
            elements.append(Paragraph('No compliance obligations extracted.', self.styles['CustomBody']))
        else:
            obligations_data = [['ID', 'Obligation', 'Category']]
            for i, obligation in enumerate(obligations, 1):
                obligations_data.append([
                    str(i),
                    obligation.get('obligation', 'N/A'),
                    obligation.get('category', 'N/A')
                ])
            
            obs_table = Table(obligations_data, colWidths=[0.5*inch, 4*inch, 1.5*inch])
            obs_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2d5a7b')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 9),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
                ('TOPPADDING', (0, 0), (-1, -1), 6),
                ('GRID', (0, 0), (-1, -1), 1, colors.lightgrey),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f5f5f5')]),
            ]))
            elements.append(obs_table)
        
        elements.append(Spacer(1, 0.3*inch))
        return elements
    
    def _build_compliance_assessment(self):
        """Build compliance assessment section"""
        elements = []
        assessment = self.report_data.get('compliance_assessment', [])
        
        elements.append(Paragraph('Compliance Assessment', self.styles['CustomHeading2']))
        
        if not assessment:
            elements.append(Paragraph('No compliance assessment data available.', self.styles['CustomBody']))
        else:
            assessment_data = [['Obligation ID', 'Status', 'Evidence']]
            for item in assessment:
                assessment_data.append([
                    str(item.get('obligation_id', 'N/A')),
                    item.get('status', 'N/A'),
                    item.get('evidence', 'N/A')[:50] + '...' if len(str(item.get('evidence', ''))) > 50 else item.get('evidence', 'N/A')
                ])
            
            assess_table = Table(assessment_data, colWidths=[1.5*inch, 1.5*inch, 3*inch])
            assess_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#406a99')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 8),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
                ('TOPPADDING', (0, 0), (-1, -1), 6),
                ('GRID', (0, 0), (-1, -1), 1, colors.lightgrey),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f9f9f9')]),
            ]))
            elements.append(assess_table)
        
        elements.append(Spacer(1, 0.3*inch))
        return elements
    
    def _build_risk_observations(self):
        """Build risk and observation summary section"""
        elements = []
        risks = self.report_data.get('risk_and_observation_summary', [])
        
        elements.append(Paragraph('Risk & Observation Summary', self.styles['CustomHeading2']))
        
        if not risks:
            elements.append(Paragraph('No risks or observations identified.', self.styles['CustomBody']))
        else:
            for i, risk in enumerate(risks, 1):
                risk_text = f"<b>[{i}] {risk.get('observation', 'N/A')}</b><br/>Severity: {risk.get('severity', 'N/A')}"
                elements.append(Paragraph(risk_text, self.styles['CustomBody']))
                elements.append(Spacer(1, 0.1*inch))
        
        elements.append(Spacer(1, 0.2*inch))
        return elements
    
    def _build_execution_trace(self):
        """Build system execution trace section"""
        elements = []
        trace = self.report_data.get('system_execution_trace', {})
        
        elements.append(Paragraph('System Execution Trace', self.styles['CustomHeading2']))
        
        trace_data = [
            ['Execution ID:', trace.get('workflow_execution_id', 'N/A')],
            ['Workflow Reference:', trace.get('workflow_reference', 'N/A')],
            ['Agents Involved:', ', '.join(trace.get('agents_involved', []))],
        ]
        
        trace_table = Table(trace_data, colWidths=[2*inch, 4*inch])
        trace_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#efefef')),
            ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ('TOPPADDING', (0, 0), (-1, -1), 6),
            ('GRID', (0, 0), (-1, -1), 1, colors.grey),
        ]))
        elements.append(trace_table)
        
        # Execution time breakdown
        timing = trace.get('execution_time_breakdown_ms', {})
        if timing:
            elements.append(Spacer(1, 0.2*inch))
            elements.append(Paragraph('Execution Time Breakdown:', self.styles['SectionHeading']))
            
            timing_data = [['Component', 'Time (ms)']]
            for component, time_ms in timing.items():
                timing_data.append([component.replace('_', ' ').title(), f"{time_ms}ms"])
            
            timing_table = Table(timing_data, colWidths=[3*inch, 1.5*inch])
            timing_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#d0d0d0')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.black),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 9),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
                ('TOPPADDING', (0, 0), (-1, -1), 6),
                ('GRID', (0, 0), (-1, -1), 1, colors.grey),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f9f9f9')]),
            ]))
            elements.append(timing_table)
        
        elements.append(Spacer(1, 0.3*inch))
        return elements
    
    def _build_limitations_and_assumptions(self):
        """Build limitations and assumptions section"""
        elements = []
        poc = self.report_data.get('poc_limitations_and_assumptions', {})
        
        elements.append(Paragraph('PoC Limitations & Assumptions', self.styles['CustomHeading2']))
        
        # Limitations
        limitations = poc.get('limitations', [])
        if limitations:
            elements.append(Paragraph('<b>Limitations:</b>', self.styles['SectionHeading']))
            for limitation in limitations:
                elements.append(Paragraph(f"• {limitation}", self.styles['CustomBody']))
            elements.append(Spacer(1, 0.15*inch))
        
        # Assumptions
        assumptions = poc.get('assumptions', [])
        if assumptions:
            elements.append(Paragraph('<b>Assumptions:</b>', self.styles['SectionHeading']))
            for assumption in assumptions:
                elements.append(Paragraph(f"• {assumption}", self.styles['CustomBody']))
        
        elements.append(Spacer(1, 0.3*inch))
        return elements
    
    def _build_conclusion(self):
        """Build conclusion section"""
        elements = []
        conclusion = self.report_data.get('conclusion', {})
        
        elements.append(Paragraph('Conclusion', self.styles['CustomHeading2']))
        
        summary = conclusion.get('summary', '')
        if summary:
            elements.append(Paragraph(summary, self.styles['CustomBody']))
        
        feasible = conclusion.get('technical_feasibility_confirmed', False)
        status_text = 'Confirmed' if feasible else 'Not Confirmed'
        elements.append(Paragraph(f"<b>Technical Feasibility:</b> {status_text}", self.styles['CustomBody']))
        
        readiness = conclusion.get('next_phase_readiness', '')
        if readiness:
            elements.append(Paragraph(f"<b>Next Phase Readiness:</b> {readiness}", self.styles['CustomBody']))
        
        elements.append(Spacer(1, 0.3*inch))
        return elements
    
    def generate_pdf(self):
        """Generate the complete PDF report"""
        if not self.load_report_data():
            return False
        
        # Create PDF document
        doc = SimpleDocTemplate(
            str(self.pdf_path),
            pagesize=letter,
            rightMargin=0.75*inch,
            leftMargin=0.75*inch,
            topMargin=0.75*inch,
            bottomMargin=0.75*inch
        )
        
        # Build document elements
        elements = []
        
        # Add all sections
        elements.extend(self._build_report_header())
        elements.append(PageBreak())
        
        elements.extend(self._build_executive_summary())
        elements.extend(self._build_rbi_circular_overview())
        elements.extend(self._build_compliance_obligations())
        
        elements.append(PageBreak())
        elements.extend(self._build_compliance_assessment())
        elements.extend(self._build_risk_observations())
        elements.extend(self._build_execution_trace())
        
        elements.append(PageBreak())
        elements.extend(self._build_limitations_and_assumptions())
        elements.extend(self._build_conclusion())
        
        # Add footer
        elements.append(Spacer(1, 0.3*inch))
        footer_text = f"Generated on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | RBI Compliance Monitoring System (PoC)"
        elements.append(Paragraph(footer_text, self.styles['FooterText']))
        
        # Build PDF
        try:
            doc.build(elements)
            logger.info(f"PDF report generated successfully: {self.pdf_path}")
            return True
        except Exception as e:
            logger.error(f"Error generating PDF: {e}")
            return False


def main():
    """Main function"""
    import sys
    
    # Setup paths
    project_root = Path(__file__).parent.parent.parent
    json_report = project_root / "reports" / "compliance_report.json"
    pdf_report = project_root / "reports" / "compliance_report.pdf"
    
    # Generate PDF
    logger.info("Starting PDF report generation...")
    generator = CompliancePDFGenerator(json_report, pdf_report)
    
    if generator.generate_pdf():
        logger.info(f"[SUCCESS] PDF report generated successfully")
        logger.info(f"Output file: {pdf_report}")
        print(f"\n{'='*80}")
        print(f"PDF REPORT GENERATED SUCCESSFULLY")
        print(f"{'='*80}")
        print(f"Report Location: {pdf_report}")
        print(f"File Size: {pdf_report.stat().st_size / 1024:.2f} KB")
        print(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'='*80}\n")
        return 0
    else:
        logger.error("[FAILED] PDF generation failed")
        print(f"\n{'='*80}")
        print(f"PDF REPORT GENERATION FAILED")
        print(f"{'='*80}\n")
        return 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
