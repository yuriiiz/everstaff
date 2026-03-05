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
        <div className="file-card file-card-entrance" onClick={() => onPreview(file)}>
            <div className="file-card-icon">
                <Icon size={18} />
            </div>
            <div className="file-card-info">
                <div className="file-card-name" title={file.file_name}>
                    {file.file_name}
                </div>
                <div className="file-card-meta">
                    {formatSize(file.size)} • {file.mime_type.split('/')[1] || file.mime_type}
                </div>
            </div>
            <div className="file-card-actions">
                <button
                    onClick={(e) => { e.stopPropagation(); onPreview(file); }}
                    title="Preview"
                    className="file-action-btn"
                >
                    <Eye size={16} />
                </button>
                <button
                    onClick={handleDownload}
                    title="Download"
                    className="file-action-btn"
                >
                    <Download size={16} />
                </button>
                <button
                    onClick={handleCopyLink}
                    title="Copy link"
                    className={`file-action-btn ${copied ? 'active' : ''}`}
                >
                    {copied ? <Check size={16} /> : <Link size={16} />}
                </button>
            </div>
        </div>
    );
}
