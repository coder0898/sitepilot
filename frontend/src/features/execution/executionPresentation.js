const notificationTones = {
  delivered: "green",
  failed: "red",
  sending: "orange",
  sent: "blue",
};

export function deliveryTone(status) {
  return notificationTones[status] || "gray";
}