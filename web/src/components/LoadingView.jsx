import React from 'react';
import { Loader2 } from 'lucide-react';

export function LoadingView({ message = 'Loading...', fullScreen = true }) {
    const containerStyle = fullScreen ? {
        height: '100%',
        width: '100%',
        flex: 1,
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        color: '#6b7280',
        minHeight: '50vh'
    } : {
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        color: '#6b7280',
        padding: '40px 24px'
    };

    return (
        <div style={containerStyle} className="loading-view fade-in">
            <Loader2 className="animate-spin mb-3 text-indigo-500" size={28} />
            <div style={{ fontSize: '14px', fontWeight: 500, color: '#64748b' }}>
                {message}
            </div>
        </div>
    );
}

export default LoadingView;
