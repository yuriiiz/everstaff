import React, { useState, useEffect, useRef } from 'react';
import { X, Download, Link, ChevronLeft } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import mermaid from 'mermaid';
import { Excalidraw } from '@excalidraw/excalidraw';
import "@excalidraw/excalidraw/index.css";
import FileBrowser from './FileBrowser';

const LANGUAGE_MAP = {
    'py': 'python', 'js': 'javascript', 'ts': 'typescript', 'jsx': 'javascript',
    'tsx': 'typescript', 'json': 'json', 'yaml': 'yaml', 'yml': 'yaml',
    'md': 'markdown', 'html': 'html', 'css': 'css', 'sh': 'shell',
    'bash': 'shell', 'sql': 'sql', 'xml': 'xml', 'csv': 'plaintext',
    'txt': 'plaintext', 'log': 'plaintext', 'toml': 'ini', 'cfg': 'ini',
    'ini': 'ini', 'rs': 'rust', 'go': 'go', 'java': 'java', 'rb': 'ruby',
    'php': 'php', 'c': 'c', 'cpp': 'cpp', 'h': 'c', 'hpp': 'cpp',
    'swift': 'swift', 'kt': 'kotlin',
};

function getLanguage(filename) {
    const ext = filename.split('.').pop()?.toLowerCase() || '';
    return LANGUAGE_MAP[ext] || 'plaintext';
}

function isTextMime(mime) {
    if (mime.startsWith('text/')) return true;
    if (['application/json', 'application/x-yaml', 'application/xml',
        'application/javascript', 'application/typescript'].includes(mime)) return true;
    return false;
}

// Monaco is lazy-loaded
let _MonacoEditor = null;
let _monacoLoading = false;

export function MermaidPreview({ chart, style = {} }) {
    const [svg, setSvg] = useState('');
    const [error, setError] = useState(null);

    useEffect(() => {
        if (!chart) return;
        mermaid.initialize({ startOnLoad: false, theme: 'default' });
        const renderChart = async () => {
            try {
                const id = `mermaid-svg-${Date.now()}`;
                const { svg } = await mermaid.render(id, chart);
                setSvg(svg);
                setError(null);
            } catch (err) {
                setError(err.message);
            }
        };
        renderChart();
    }, [chart]);

    if (error) {
        return <div style={{ color: '#ef4444', padding: '20px' }}>Failed to render Mermaid chart: {error}</div>;
    }
    return (
        <div
            style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', padding: '20px', width: '100%', height: '100%', overflow: 'auto', ...style }}
            dangerouslySetInnerHTML={{ __html: svg }}
        />
    );
}

export default function FilePreviewModal({ file, sessionId, onClose }) {
    const [activeFile, setActiveFile] = useState(file);
    const [content, setContent] = useState(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const [copied, setCopied] = useState(false);
    const [monacoReady, setMonacoReady] = useState(!!_MonacoEditor);

    const fileUrl = `/api/sessions/${sessionId}/files/${encodeURIComponent(activeFile.file_path)}`;
    const mime = activeFile.mime_type;
    const isDir = mime === 'inode/directory';

    // Fetch text content
    useEffect(() => {
        if (isDir) {
            setLoading(false);
            return;
        }
        if (!isTextMime(mime) && mime !== 'application/pdf') {
            setLoading(false);
            return;
        }
        if (mime === 'application/pdf') {
            setLoading(false);
            return;
        }
        setLoading(true);
        fetch(fileUrl)
            .then(r => {
                if (!r.ok) throw new Error(`HTTP ${r.status}`);
                return r.text();
            })
            .then(text => { setContent(text); setLoading(false); })
            .catch(err => { setError(err.message); setLoading(false); });
    }, [fileUrl, mime, isDir]);

    // Lazy-load Monaco
    useEffect(() => {
        if (isTextMime(mime) && mime !== 'text/markdown' && mime !== 'text/html' && !_MonacoEditor && !_monacoLoading) {
            _monacoLoading = true;
            import('@monaco-editor/react').then(mod => {
                _MonacoEditor = mod.default;
                _monacoLoading = false;
                setMonacoReady(true);
            }).catch(() => { _monacoLoading = false; });
        }
    }, [mime]);

    // ESC to close
    useEffect(() => {
        const handler = (e) => { if (e.key === 'Escape') onClose(); };
        window.addEventListener('keydown', handler);
        return () => window.removeEventListener('keydown', handler);
    }, [onClose]);

    const handleDownload = () => {
        const a = document.createElement('a');
        a.href = `${fileUrl}?download=true`;
        a.download = isDir ? `${activeFile.file_name}.zip` : activeFile.file_name;
        a.click();
    };

    const handleCopyLink = async () => {
        const url = `${window.location.origin}${fileUrl}`;
        try {
            await navigator.clipboard.writeText(url);
            setCopied(true);
            setTimeout(() => setCopied(false), 2000);
        } catch {
            const input = document.createElement('input');
            input.value = url;
            document.body.appendChild(input);
            input.select();
            document.execCommand('copy');
            document.body.removeChild(input);
            setCopied(true);
            setTimeout(() => setCopied(false), 2000);
        }
    };

    const renderContent = () => {
        if (loading) {
            return <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100%', color: '#9ca3af' }}>Loading...</div>;
        }
        if (error) {
            return <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100%', color: '#ef4444' }}>Error: {error}</div>;
        }

        // Folder
        if (isDir) {
            return (
                <div style={{ height: '100%', background: '#fff' }}>
                    <FileBrowser sessionId={sessionId} onPreview={setActiveFile} initialPath={activeFile.file_path} />
                </div>
            );
        }

        // Excalidraw
        if (activeFile.file_name.endsWith('.excalidraw')) {
            let initialData = null;
            try {
                if (content) {
                    const parsed = JSON.parse(content);
                    initialData = {
                        elements: parsed.elements || [],
                        appState: parsed.appState || {},
                        files: parsed.files || {}
                    };
                }
            } catch (e) { }
            return (
                <div style={{ height: '100%', width: '100%', position: 'relative' }}>
                    {initialData ? <Excalidraw initialData={initialData} viewModeEnabled={true} UIOptions={{ canvasActions: { loadScene: false, export: false, saveAsImage: false } }} /> : <div>Parsing...</div>}
                </div>
            );
        }

        // Mermaid
        if (activeFile.file_name.endsWith('.mermaid') || activeFile.file_name.endsWith('.mmd')) {
            return <MermaidPreview chart={content} />;
        }

        // Markdown
        if (mime === 'text/markdown') {
            return (
                <div style={{ padding: '20px', overflow: 'auto', height: '100%' }}>
                    <ReactMarkdown remarkPlugins={[remarkGfm]} components={{
                        table: ({ node, ...props }) => <table style={{ borderCollapse: 'collapse', width: '100%' }} {...props} />,
                        th: ({ node, ...props }) => <th style={{ border: '1px solid #e5e7eb', padding: '8px 12px', background: '#f9fafb', textAlign: 'left' }} {...props} />,
                        td: ({ node, ...props }) => <td style={{ border: '1px solid #e5e7eb', padding: '8px 12px' }} {...props} />,
                        pre: ({ node, ...props }) => <pre style={{ background: '#f3f4f6', borderRadius: '6px', padding: '12px', overflow: 'auto' }} {...props} />,
                        code: ({ node, inline, ...props }) => <code style={{ background: inline ? '#f3f4f6' : 'transparent', padding: inline ? '2px 4px' : 0, borderRadius: '3px', fontSize: '13px' }} {...props} />,
                    }}>
                        {content}
                    </ReactMarkdown>
                </div>
            );
        }

        // HTML
        if (mime === 'text/html') {
            return (
                <iframe
                    sandbox="allow-scripts"
                    srcDoc={content}
                    style={{ width: '100%', height: '100%', border: 'none' }}
                    title={activeFile.file_name}
                />
            );
        }

        // Image
        if (mime.startsWith('image/')) {
            return (
                <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100%', padding: '20px', overflow: 'auto' }}>
                    <img src={fileUrl} alt={activeFile.file_name} style={{ maxWidth: '100%', maxHeight: '100%', objectFit: 'contain' }} />
                </div>
            );
        }

        // Video
        if (mime.startsWith('video/')) {
            return (
                <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100%', padding: '20px' }}>
                    <video controls src={fileUrl} style={{ maxWidth: '100%', maxHeight: '100%' }}>
                        Your browser does not support the video tag.
                    </video>
                </div>
            );
        }

        // PDF
        if (mime === 'application/pdf') {
            return <iframe src={fileUrl} style={{ width: '100%', height: '100%', border: 'none' }} title={activeFile.file_name} />;
        }

        // Text / Code (Monaco)
        if (isTextMime(mime) && _MonacoEditor) {
            const MonacoEditor = _MonacoEditor;
            return (
                <MonacoEditor
                    height="100%"
                    language={getLanguage(activeFile.file_name)}
                    value={content || ''}
                    options={{
                        readOnly: true,
                        minimap: { enabled: false },
                        scrollBeyondLastLine: false,
                        fontSize: 13,
                        wordWrap: 'on',
                        lineNumbers: 'on',
                    }}
                    theme="vs-light"
                />
            );
        }

        // Text fallback (Monaco not loaded)
        if (isTextMime(mime) && content !== null) {
            return (
                <pre style={{ padding: '20px', margin: 0, overflow: 'auto', height: '100%', fontSize: '13px', fontFamily: 'monospace' }}>
                    {content}
                </pre>
            );
        }

        // Unsupported
        return (
            <div style={{ display: 'flex', flexDirection: 'column', justifyContent: 'center', alignItems: 'center', height: '100%', gap: '12px', color: '#6b7280' }}>
                <p>Preview not available for this file type.</p>
                <button onClick={handleDownload} style={{
                    padding: '8px 16px', background: '#3b82f6', color: 'white', border: 'none',
                    borderRadius: '6px', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '6px',
                }}>
                    <Download size={14} /> Download
                </button>
            </div>
        );
    };

    return (
        <div
            style={{
                position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
                background: 'rgba(0,0,0,0.5)', zIndex: 9999,
                display: 'flex', justifyContent: 'center', alignItems: 'center',
            }}
            onClick={onClose}
        >
            <div
                style={{
                    width: 'min(98vw, 1600px)', height: 'min(96vh, 1000px)',
                    background: 'white', borderRadius: '12px',
                    display: 'flex', flexDirection: 'column',
                    boxShadow: '0 20px 60px rgba(0,0,0,0.3)',
                    overflow: 'hidden',
                }}
                onClick={e => e.stopPropagation()}
            >
                {/* Header */}
                <div style={{
                    display: 'flex', alignItems: 'center', gap: '12px',
                    padding: '14px 20px', borderBottom: '1px solid #f3f4f6',
                    flexShrink: 0,
                    background: 'rgba(255, 255, 255, 0.8)',
                    backdropFilter: 'blur(8px)',
                    zIndex: 10,
                }}>
                    {activeFile.file_path !== file.file_path && (
                        <button
                            onClick={() => setActiveFile(file)}
                            style={{ background: 'none', border: 'none', cursor: 'pointer', display: 'flex', color: '#6b7280', padding: 0 }}
                            title="Back to root"
                        >
                            <ChevronLeft size={20} />
                        </button>
                    )}
                    <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ fontWeight: 600, fontSize: '14px', color: '#111827', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                            {activeFile.file_name}
                        </div>
                        <div style={{ fontSize: '11px', color: '#9ca3af' }}>
                            {activeFile.mime_type} • {activeFile.size ? (activeFile.size / 1024).toFixed(1) + ' KB' : (isDir ? 'Folder' : '--')}
                        </div>
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                        <button onClick={handleCopyLink} title="Copy link" style={{
                            background: 'white', border: '1px solid #e5e7eb', borderRadius: '8px',
                            padding: '6px 12px', cursor: 'pointer', fontSize: '12px', color: '#4b5563',
                            display: 'flex', alignItems: 'center', gap: '6px',
                            transition: 'all 0.2s', fontWeight: 500,
                        }}>
                            <Link size={14} /> {copied ? 'Copied!' : 'Copy Link'}
                        </button>
                        <button onClick={handleDownload} title="Download" style={{
                            background: '#111827', border: '1px solid #111827', borderRadius: '8px',
                            padding: '6px 12px', cursor: 'pointer', fontSize: '12px', color: 'white',
                            display: 'flex', alignItems: 'center', gap: '6px',
                            transition: 'all 0.2s', fontWeight: 500,
                        }}>
                            <Download size={14} /> Download
                        </button>
                        <button onClick={onClose} title="Close" style={{
                            background: 'none', border: 'none', cursor: 'pointer', padding: '4px', color: '#9ca3af',
                            display: 'flex',
                        }}>
                            <X size={18} />
                        </button>
                    </div>
                </div>

                {/* Content */}
                <div style={{ flex: 1, overflow: 'hidden' }}>
                    {renderContent()}
                </div>
            </div>
        </div>
    );
}

