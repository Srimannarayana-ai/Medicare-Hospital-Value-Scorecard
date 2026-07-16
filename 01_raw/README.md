# Raw CMS files

Download the hospital CSVs from:
https://data.cms.gov/provider-data/topics/hospitals

Put these files in this folder (same names):

- Hospital_General_Information.csv
- HCAHPS-Hospital.csv
- Unplanned_Hospital_Visits-Hospital.csv
- Healthcare_Associated_Infections-Hospital.csv
- Medicare_Hospital_Spending_Per_Patient-Hospital.csv

They are not committed to GitHub because a few of them are very large.

After downloading, rebuild the clean tables with:

```bash
python scripts/build_scorecard.py
```
