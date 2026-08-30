// QR Attendance & Scanner Helpers

async function submitQrScan(qrPayload) {
  try {
    const res = await fetch('/api/attendance/scan-qr', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ qr_data: qrPayload })
    });
    const data = await res.json();
    
    const banner = document.getElementById('qr-status-banner');
    if (banner) {
      if (data.status === 'MARKED') {
        banner.className = 'status-banner success';
        banner.innerHTML = `<strong>✓ Marked PRESENT:</strong> ${data.student.name} (${data.student.roll_no})`;
        showToast(data.message, 'success');
      } else if (data.status === 'ALREADY_MARKED') {
        banner.className = 'status-banner warning';
        banner.innerHTML = `<strong>⚠ Already Marked Today:</strong> ${data.student.name}`;
        showToast(data.message, 'error');
      } else {
        banner.className = 'status-banner danger';
        banner.innerHTML = `<strong>✗ Not Found:</strong> ${data.message}`;
        showToast(data.message, 'error');
      }
    }
  } catch (err) {
    console.error('QR scan submission error:', err);
  }
}
