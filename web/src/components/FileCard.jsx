import React from 'react';
import { FileText, Image, Film, Globe, File, Download, Link, Eye, Check } from 'lucide-react';

const ICON_MAP = {
    'text/': FileText,
    'image/': Image,
    'video/': Film,
    'text/html': Globe,
    'application/pdf': FileText,
};

function getFileIcon(mimeType) {
    if (ICON_MAP[mimeType]) return ICON_MAP[mimeType];
    for (const [prefix, Icon] of Object.entries(ICON_MAP)) {
        if (mimeType.startsWith(prefix)) return Icon;
    }
    return File;
}

function formatSize(bytes) {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export default function FileCard({ file, sessionId, onPreview }) {
    const [copied, setCopied] = React.useState(false);
    const Icon = getFileIcon(file.mime_type);
    const fileUrl = `/api/sessions/${sessionId}/files/${encodeURIComponent(file.file_path)}`;

    const handleDownload = (e) => {
        e.stopPropagation();
        const a = document.createElement('a');
        a.href = `${fileUrl}?download=true`;
        a.download = file.file_name;
        a.click();
    };

    const handleCopyLink = async (e) => {
        e.stopPropagation();
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

    return (
        <div
            style={{
                display: 'flex',
                alignItems: 'center',
                gap: '10px',
                padding: '8px 12px',
                border: '1px solid #e5e7eb',
                borderRadius: '8px',
                background: '#fafbfc',
                cursor: 'pointer',
                transition: 'border-color 0.15s',
                fontSize: '12.5px',
            }}
            onClick={() => onPreview(file)}
            onMouseEnter={e => e.currentTarget.style.borderColor = '#3b82f6'}
            onMouseLeave={e => e.currentTarget.style.borderColor = '#e5e7eb'}
        >
            <Icon size={16} style={{ color: '#6b7280', flexShrink: 0 }} />
            <span style={{ fontWeight: 500, color: '#111827', flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {file.file_name}
            </span>
            <span style={{ color: '#9ca3af', fontSize: '11px', flexShrink: 0 }}>
                {formatSize(file.size)}
            </span>
            <button
                onClick={(e) => { e.stopPropagation(); onPreview(file); }}
                title="Preview"
                style={{ background: 'none', border: 'none', cursor: 'pointer', padding: '2px', color: '#6b7280', display: 'flex' }}
            >
                <Eye size={14} />
            </button>
            <button
                onClick={handleDownload}
                title="Download"
                style={{ background: 'none', border: 'none', cursor: 'pointer', padding: '2px', color: '#6b7280', display: 'flex' }}
            >
                <Download size={14} />
            </button>
            <button
                onClick={handleCopyLink}
                title="Copy link"
                style={{ background: 'none', border: 'none', cursor: 'pointer', padding: '2px', color: copied ? '#10b981' : '#6b7280', display: 'flex', transition: 'color 0.2s' }}
            >
                {copied ? <Check size={14} /> : <Link size={14} />}
            </button>
        </div>
    );
}
