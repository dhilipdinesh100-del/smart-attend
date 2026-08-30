// Client-side Attendance Search & Filter Utilities

function filterAttendanceTable(inputId, tableId) {
  const input = document.getElementById(inputId);
  const filter = input.value.toLowerCase();
  const table = document.getElementById(tableId);
  if (!table) return;

  const rows = table.getElementsByTagName('tr');
  for (let i = 1; i < rows.length; i++) {
    const text = rows[i].textContent.toLowerCase();
    rows[i].style.display = text.includes(filter) ? '' : 'none';
  }
}
