function calculateDaysBetweenDates(begin, end) {
  const beginDate = new Date(begin);
  const endDate = new Date(end);
  const beginYear = beginDate.getFullYear();
  const endYear = endDate.getFullYear();
  const beginMonth = beginDate.getMonth();
  const endMonth = endDate.getMonth();
  const beginDay = beginDate.getDate();
  const endDay = endDate.getDate();
  const beginDateInDays = beginDay + (beginMonth * 30) + (beginYear * 365);
  const endDateInDays = endDay + (endMonth * 30) + (endYear * 365);
  return endDateInDays - beginDateInDays;
}
