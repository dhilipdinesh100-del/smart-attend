// Real-Time Dashboard Analytics & Chart.js Controllers

let methodChart = null;
let trendChart = null;

document.addEventListener('DOMContentLoaded', () => {
  initDashboardCharts();
  startDashboardPolling();
});

function initDashboardCharts() {
  const methodCanvas = document.getElementById('methodChart');
  const trendCanvas = document.getElementById('trendChart');

  // Attendance by Method Donut Chart
  if (methodCanvas && window.dashboardData) {
    const ctx = methodCanvas.getContext('2d');
    const faceCount = window.dashboardData.stats.face_total || 0;
    const qrCount = window.dashboardData.stats.qr_total || 0;
    const manualCount = window.dashboardData.stats.manual_total || 0;

    methodChart = new Chart(ctx, {
      type: 'doughnut',
      data: {
        labels: ['Face Recognition', 'QR Code', 'Manual Log'],
        datasets: [{
          data: [faceCount, qrCount, manualCount],
          backgroundColor: ['#38bdf8', '#c084fc', '#2dd4bf'],
          borderWidth: 0,
          hoverOffset: 6
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: {
            position: 'bottom',
            labels: {
              color: '#94a3b8',
              boxWidth: 12,
              padding: 16,
              font: { family: 'Plus Jakarta Sans', size: 12, weight: '600' }
            }
          },
          tooltip: {
            backgroundColor: '#111827',
            titleColor: '#f8fafc',
            bodyColor: '#94a3b8',
            borderColor: 'rgba(255, 255, 255, 0.1)',
            borderWidth: 1,
            padding: 12,
            boxPadding: 6,
            usePointStyle: true
          }
        },
        cutout: '72%'
      }
    });
  }

  // 7-Day Attendance Trend Area Chart
  if (trendCanvas && window.dashboardData) {
    const ctx = trendCanvas.getContext('2d');
    const trends = window.dashboardData.trends;

    trendChart = new Chart(ctx, {
      type: 'line',
      data: {
        labels: trends.labels,
        datasets: [
          {
            label: 'Total Present',
            data: trends.present,
            borderColor: '#6366f1',
            backgroundColor: 'rgba(99, 102, 241, 0.14)',
            fill: true,
            tension: 0.35,
            borderWidth: 2.5,
            pointRadius: 4,
            pointBackgroundColor: '#6366f1',
            pointBorderColor: '#090d16',
            pointBorderWidth: 2
          },
          {
            label: 'Face Scans',
            data: trends.face,
            borderColor: '#38bdf8',
            borderDash: [4, 4],
            tension: 0.35,
            borderWidth: 2,
            pointRadius: 3,
            pointBackgroundColor: '#38bdf8'
          },
          {
            label: 'QR Scans',
            data: trends.qr,
            borderColor: '#c084fc',
            borderDash: [4, 4],
            tension: 0.35,
            borderWidth: 2,
            pointRadius: 3,
            pointBackgroundColor: '#c084fc'
          },
          {
            label: 'Manual Logs',
            data: trends.manual || [],
            borderColor: '#2dd4bf',
            borderDash: [2, 2],
            tension: 0.35,
            borderWidth: 2,
            pointRadius: 3,
            pointBackgroundColor: '#2dd4bf'
          }
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        scales: {
          x: {
            grid: { color: 'rgba(255, 255, 255, 0.04)' },
            ticks: { color: '#64748b', font: { family: 'Plus Jakarta Sans', size: 11, weight: '500' } }
          },
          y: {
            beginAtZero: true,
            grid: { color: 'rgba(255, 255, 255, 0.04)' },
            ticks: { color: '#64748b', stepSize: 1, font: { family: 'Plus Jakarta Sans', size: 11 } }
          }
        },
        plugins: {
          legend: {
            position: 'top',
            labels: {
              color: '#94a3b8',
              boxWidth: 10,
              padding: 12,
              font: { family: 'Plus Jakarta Sans', size: 11.5, weight: '600' }
            }
          },
          tooltip: {
            backgroundColor: '#111827',
            titleColor: '#f8fafc',
            bodyColor: '#94a3b8',
            borderColor: 'rgba(255, 255, 255, 0.1)',
            borderWidth: 1,
            padding: 12
          }
        }
      }
    });
  }
}

let dashboardPollInterval = null;

function startDashboardPolling() {
  if (dashboardPollInterval) clearInterval(dashboardPollInterval);
  dashboardPollInterval = setInterval(async () => {
    try {
      const res = await fetch('/api/dashboard');
      if (!res.ok) return;
      const data = await res.json();
      if (data.status === 'success') {
        updateDashboardUI(data);
      }
    } catch (e) {
      console.warn('Dashboard poll error:', e);
    }
  }, 3000);
}

window.addEventListener('pagehide', () => {
  if (dashboardPollInterval) clearInterval(dashboardPollInterval);
});
window.addEventListener('beforeunload', () => {
  if (dashboardPollInterval) clearInterval(dashboardPollInterval);
});

function updateDashboardUI(data) {
  const stats = data.stats;
  const trends = data.trends;

  // Update Counters
  updateText('stat-total-students', stats.total_students);
  updateText('stat-today-present', stats.today_present);
  updateText('stat-today-absent', stats.today_absent);
  updateText('stat-attendance-rate', `${stats.attendance_rate}%`);
  updateText('stat-face-today', stats.face_today);
  updateText('stat-qr-today', stats.qr_today);
  updateText('stat-manual-today', stats.manual_today || 0);
  updateText('stat-face-total', stats.face_total);
  updateText('stat-qr-total', stats.qr_total);
  updateText('stat-manual-total', stats.manual_total || 0);

  // Update Charts
  if (methodChart) {
    methodChart.data.datasets[0].data = [
      stats.face_total || 0,
      stats.qr_total || 0,
      stats.manual_total || 0
    ];
    methodChart.update('none');
  }

  if (trendChart && trends) {
    trendChart.data.labels = trends.labels;
    trendChart.data.datasets[0].data = trends.present;
    trendChart.data.datasets[1].data = trends.face;
    trendChart.data.datasets[2].data = trends.qr;
    if (trendChart.data.datasets[3]) {
      trendChart.data.datasets[3].data = trends.manual || [];
    }
    trendChart.update('none');
  }

  // Update Recent Attendance Table
  const tbody = document.getElementById('recent-attendance-tbody');
  if (tbody && stats.recent_records) {
    if (stats.recent_records.length === 0) {
      tbody.innerHTML = `<tr><td colspan="5" class="empty-state" style="padding: 20px;"><p style="margin: 0;">No attendance records recorded yet today.</p></td></tr>`;
    } else {
      tbody.innerHTML = stats.recent_records.map(r => {
        let badgeClass = 'badge-manual';
        if (r.method === 'FACE') badgeClass = 'badge-face';
        else if (r.method === 'QR') badgeClass = 'badge-qr';
        return `
          <tr>
            <td><span style="font-weight: 600;">${r.name}</span></td>
            <td><span style="font-family: 'JetBrains Mono', monospace; font-size: 12px; color: var(--text-muted);">${r.roll_no}</span></td>
            <td>
              <span class="badge ${badgeClass}">
                ${r.method}
              </span>
            </td>
            <td><span style="font-size: 12.5px; color: var(--text-muted); font-family: 'JetBrains Mono', monospace;">${r.time}</span></td>
            <td><span class="badge badge-present">PRESENT</span></td>
          </tr>
        `;
      }).join('');
    }
  }
}

function updateText(elId, val) {
  const el = document.getElementById(elId);
  if (el && el.textContent !== String(val)) {
    el.textContent = val;
  }
}
