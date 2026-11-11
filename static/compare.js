// AI citation: drafted by Claude (Anthropic).
// The Compare button works only when exactly two runs are selected.
const boxes = document.querySelectorAll('#compare input[name="run"]');
const button = document.getElementById("compare-btn");
const hint = document.getElementById("compare-hint");

function update() {
  const count = document.querySelectorAll('#compare input[name="run"]:checked').length;
  button.disabled = count !== 2;
  // With two selected, the others lock; clear one to change the selection.
  boxes.forEach((box) => { box.disabled = count >= 2 && !box.checked; });
  hint.textContent = count === 2 ? "" : `Select two runs (${count} selected).`;
}

boxes.forEach((box) => box.addEventListener("change", update));
update();
