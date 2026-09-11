import fs from "node:fs/promises";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const outputDir = "D:/dev/literature-platform/outputs/excel_data_20260910";
const outputPath = `${outputDir}/experiment_data.xlsx`;
const font = "Arial";

const records = [
  ["15cm","64g","FWB",409.076,395.873,395.254,340.175,445.925,"第4个数据前有笔误涂黑块"],
  ["15cm","64g","JL",233.109,273.336,283.032,251.057,244.406,""],
  ["15cm","64g","70po",401.650,375.038,363.898,424.142,465.600,""],
  ["15cm","64g","HJ",453.429,488.498,478.308,466.219,504.589,"原数据477.803划掉，重写为478.308"],
  ["15cm","64g","NZN",414.852,464.568,467.950,491.386,469.726,""],
  ["15cm","64g","NZN 10",482.928,440.020,441.876,487.467,415.265,""],
  ["15cm","110g","FWB",615.367,581.742,536.770,633.727,576.791,""],
  ["15cm","110g","JL",401.031,402.268,420.628,343.475,337.493,""],
  ["15cm","110g","70po",549.148,548.116,577.204,560.494,508.096,""],
  ["15cm","110g","HJ",601.133,664.465,670.447,676.224,670.241,""],
  ["15cm","110g","NZN",617.137,575.760,518.137,636.409,480.453,""],
  ["15cm","110g","NZN 10",589.168,551.417,538.833,595.770,543.372,"第2个数据原585.417划掉，改为551.417"],
  ["15cm","256g","FWB",713.097,749.457,775.450,669.003,669.828,"原纸右上斜向书写排布"],
  ["15cm","256g","JL",762.041,768.642,728.415,747.188,792.159,""],
  ["15cm","256g","70po",801.649,763.279,740.999,805.775,725.733,"第5个数据前涂抹纠正"],
  ["15cm","256g","HJ",815.264,814.439,768.436,735.363,758.534,""],
  ["15cm","256g","NZN",802.474,783.701,744.300,738.111,745.950,""],
  ["15cm","256g","NZN 10",780.813,769.467,767.611,837.337,694.583,"第4个数据前涂抹纠正"],
  ["10cm","64g","FWB",197.834,194.739,201.959,200.722,173.904,"第4项原207.22划掉，上方更正为200.722"],
  ["10cm","64g","JL",109.770,112.429,90.768,74.894,87.468,""],
  ["10cm","64g","70po",330.066,317.276,326.766,309.640,428.516,"原首项300.066划掉，更正为330.066"],
  ["10cm","64g","HS",326.430,444.197,592.263,455.698,617.843,""],
  ["10cm","64g","NZN",270.861,322.021,305.311,304.486,261.784,""],
  ["10cm","64g","NZN 10",402.681,376.688,386.178,368.643,380.195,""],
  ["10cm","110g","FWB",454.666,400.824,458.586,387.622,494.068,""],
  ["10cm","110g","JL",124.600,120.887,152.656,150.180,126.869,""],
  ["10cm","110g","70po",508.921,440.767,482.510,469.107,404.950,"首项划改后更正为508.921"],
  ["10cm","110g","HS",403.919,424.135,448.271,433.025,416.296,""],
  ["10cm","110g","NZN",455.079,444.971,432.387,466.291,493.862,""],
  ["10cm","110g","NZN 10",404.125,416.296,449.303,453.222,437.751,""],
  ["10cm","256g","FWB",558.018,536.358,594.120,613.511,619.448,""],
  ["10cm","256g","JL",314.206,333.367,344.919,366.993,368.230,""],
  ["10cm","256g","70po",656.213,682.619,628.570,641.979,691.695,"含两处划改，保留最终有效5次数据"],
  ["10cm","256g","HJ",562.351,607.322,575.966,594.945,587.106,""],
  ["10cm","256g","NZN",641.360,671.273,596.389,628.983,630.633,""],
  ["10cm","256g","NZN 10",580.504,565.239,559.256,559.669,583.599,"前两项错误划掉，保留后面有效5次数据"],
];

const workbook = Workbook.create();
const overview = workbook.worksheets.add("数据总览");
const raw = workbook.worksheets.add("原始记录");

function styleTable(sheet, range, headerRange) {
  range.format.font = { name: font, size: 10, color: "#1F2937" };
  range.format.verticalAlignment = "center";
  range.format.borders = { preset: "all", style: "thin", color: "#D9E1E8" };
  headerRange.format = {
    fill: "#1F4E78",
    font: { name: font, size: 10, bold: true, color: "#FFFFFF" },
    horizontalAlignment: "center",
    verticalAlignment: "center",
    borders: { preset: "all", style: "thin", color: "#FFFFFF" },
  };
}

overview.showGridLines = false;
overview.getRange("A1:J1").merge();
overview.getRange("A1").values = [["实验数据汇总"]];
overview.getRange("A1").format = { font: { name: font, size: 15, bold: true, color: "#17365D" }, horizontalAlignment: "left", verticalAlignment: "center" };
overview.getRange("A1:J1").format.rowHeight = 28;
overview.getRange("A2").values = [["每组含 5 次测试；平均值与标准差均由 Excel 公式自动计算。"]];
overview.getRange("A2").format = { font: { name: font, size: 10, italic: true, color: "#5B6573" } };
const headers = [["测试高度","冲击重量","样品编号","第1次","第2次","第3次","第4次","第5次","平均值","标准差"]];
overview.getRange("A4:J4").values = headers;
const overviewValues = records.map(r => r.slice(0, 8).concat([null, null]));
overview.getRange(`A5:J${4 + records.length}`).values = overviewValues;
overview.getRange(`I5:I${4 + records.length}`).formulas = records.map((_, i) => [`=AVERAGE(D${5+i}:H${5+i})`]);
overview.getRange(`J5:J${4 + records.length}`).formulas = records.map((_, i) => [`=STDEV.S(D${5+i}:H${5+i})`]);
styleTable(overview, overview.getRange(`A4:J${4 + records.length}`), overview.getRange("A4:J4"));
overview.getRange(`D5:J${4 + records.length}`).format.numberFormat = "0.000";
overview.getRange(`A5:C${4 + records.length}`).format.horizontalAlignment = "center";
overview.getRange(`D5:J${4 + records.length}`).format.horizontalAlignment = "right";
overview.getRange(`I5:J${4 + records.length}`).format.font = { name: font, size: 10, bold: true, color: "#17365D" };
overview.getRange(`A4:J${4 + records.length}`).format.autofitColumns();
overview.getRange("A:A").format.columnWidth = 12;
overview.getRange("B:B").format.columnWidth = 12;
overview.getRange("C:C").format.columnWidth = 13;
overview.getRange("D:J").format.columnWidth = 12;
overview.freezePanes.freezeRows(4);
overview.tabColor = "#1F4E78";

raw.showGridLines = false;
raw.getRange("A1:K1").merge();
raw.getRange("A1").values = [["原始测试记录"]];
raw.getRange("A1").format = { font: { name: font, size: 15, bold: true, color: "#17365D" }, horizontalAlignment: "left", verticalAlignment: "center" };
raw.getRange("A1:K1").format.rowHeight = 28;
raw.getRange("A2").values = [["保留用户提供的有效读数；涂改说明单列记录，方便追溯。"]];
raw.getRange("A2").format = { font: { name: font, size: 10, italic: true, color: "#5B6573" } };
raw.getRange("A4:K4").values = [["测试高度","冲击重量","样品编号","第1次","第2次","第3次","第4次","第5次","平均值","标准差","原始说明"]];
raw.getRange(`A5:K${4 + records.length}`).values = records.map(r => r.slice(0, 8).concat([null, null, r[8]]));
raw.getRange(`I5:I${4 + records.length}`).formulas = records.map((_, i) => [`=AVERAGE(D${5+i}:H${5+i})`]);
raw.getRange(`J5:J${4 + records.length}`).formulas = records.map((_, i) => [`=STDEV.S(D${5+i}:H${5+i})`]);
styleTable(raw, raw.getRange(`A4:K${4 + records.length}`), raw.getRange("A4:K4"));
raw.getRange(`D5:J${4 + records.length}`).format.numberFormat = "0.000";
raw.getRange(`A5:C${4 + records.length}`).format.horizontalAlignment = "center";
raw.getRange(`D5:J${4 + records.length}`).format.horizontalAlignment = "right";
raw.getRange(`K5:K${4 + records.length}`).format.wrapText = false;
raw.getRange(`A4:K${4 + records.length}`).format.autofitColumns();
raw.getRange("A:A").format.columnWidth = 12;
raw.getRange("B:B").format.columnWidth = 12;
raw.getRange("C:C").format.columnWidth = 13;
raw.getRange("D:J").format.columnWidth = 12;
raw.getRange("K:K").format.columnWidth = 38;
raw.freezePanes.freezeRows(4);
raw.tabColor = "#9FBAD0";

workbook.recalculate();
const keyCheck = await workbook.inspect({ kind: "table", range: "数据总览!A1:J12", include: "values,formulas", tableMaxRows: 12, tableMaxCols: 10 });
console.log(keyCheck.ndjson);
const errors = await workbook.inspect({ kind: "match", searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!", options: { useRegex: true, maxResults: 100 }, summary: "formula error scan" });
console.log(errors.ndjson);
const preview = await workbook.render({ sheetName: "数据总览", range: "A1:J18", scale: 1.5, format: "png" });
await fs.writeFile(`${outputDir}/overview_preview.png`, new Uint8Array(await preview.arrayBuffer()));
const exported = await SpreadsheetFile.exportXlsx(workbook);
await exported.save(outputPath);
console.log(`SAVED ${outputPath}`);
