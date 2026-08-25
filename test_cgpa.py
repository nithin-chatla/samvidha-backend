from bs4 import BeautifulSoup
import re

html_content = """
<tr class="bg-danger">
<td colspan="9" style='text-align:right;padding-right:10px;'>Semester Grade Point Average (SGPA) : 6.95 </td>
</tr>
<tr class="bg-teal">
<td colspan="9" style='text-align:right;padding-right:10px;'>Cumulative Grade Point Average (CGPA) : 6.95 </td>
</tr>
<div class="watermark sem2">24951A66C7</div>
<tr class="text-center bg-lightblue disabled">
<th colspan="9" >II SEMESTER</th>
</tr>
<tr class="bg-danger">
<td colspan="9" style='text-align:right;padding-right:10px;'>Semester Grade Point Average (SGPA) : 5.55 </td>
</tr>
<tr class="bg-teal">
<td colspan="9" style='text-align:right;padding-right:10px;'>Cumulative Grade Point Average (CGPA) : 6.25 </td>
</tr>
<div class="watermark sem3">24951A66C7</div>
<tr class="text-center bg-lightblue disabled">
<th colspan="9" >III SEMESTER</th>
</tr>
<tr class="bg-danger">
<td colspan="9" style='text-align:right;padding-right:10px;'>Semester Grade Point Average (SGPA) : 6.6 </td>
</tr>
<tr class="bg-teal">
<td colspan="9" style='text-align:right;padding-right:10px;'>Cumulative Grade Point Average (CGPA) : 6.37 </td>
</tr>
<div class="watermark sem4">24951A66C7</div>
<tr class="text-center bg-lightblue disabled">
<th colspan="9" >IV SEMESTER </th>
</tr>
<tr class="bg-danger">
<td colspan="9" style='text-align:right;padding-right:10px;'>Semester Grade Point Average (SGPA) : 7.1 </td>
</tr>
<tr class="bg-teal">
<td colspan="9" style='text-align:right;padding-right:10px;'>Cumulative Grade Point Average (CGPA) : 6.55 </td>
</tr>
<div class="watermark sem5">24951A66C7</div>
<tr class="text-center bg-lightblue disabled">
<th colspan="9" >V SEMESTER</th>
</tr>
<tr class="bg-danger">
<td colspan="9" style='text-align:right;padding-right:10px;'>Semester Grade Point Average (SGPA) : - </td>
</tr>
<tr class="bg-teal">
<td colspan="9" style='text-align:right;padding-right:10px;'>Cumulative Grade Point Average (CGPA) : 6.55 </td>
</tr>
"""

soup = BeautifulSoup(html_content, "lxml")
results_data = []
current_sem_data = {"sem": "test", "subjects": []}
overall_cgpa = "N/A"

rows = soup.find_all('tr')
for row in rows:
    text = row.get_text(separator=' ', strip=True).upper()
    if "CUMULATIVE GRADE POINT AVERAGE" in text:
        match = re.search(r'CGPA[^\d]*([\d\.]+)', text)
        if match: 
            if current_sem_data:
                current_sem_data["cgpa"] = match.group(1)
            overall_cgpa = match.group(1) 
        continue

print("Overall CGPA:", overall_cgpa)
