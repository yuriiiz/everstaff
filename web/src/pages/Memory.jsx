import MemoryList from '../components/MemoryList';

export default function Memory() {
    return (
        <div style={{ display: 'flex', flexDirection: 'column', height: '100%', background: '#f9fafb' }}>
            <div style={{ padding: '0 24px', background: 'white', borderBottom: '1px solid #e5e7eb', display: 'flex', justifyContent: 'space-between', alignItems: 'center', height: '60px', flexShrink: 0 }}>
                <div>
                    <h1 style={{ fontSize: '15px', fontWeight: 700, color: '#111827', margin: 0 }}>Memory</h1>
                </div>
            </div>

            <div style={{ flex: 1, overflow: 'hidden' }}>
                <MemoryList />
            </div>
        </div>
    );
}
