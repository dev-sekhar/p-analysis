# Portfolio Dashboard Development Prompts

Here is a chronological log of the prompts and requests you used to build and refine the `p-analysis` portfolio dashboard project:

### Phase 1: Core Dashboard & Heatmaps
1. **Initial Issue:** "perf heat map - Upload Summary CSV with P/L % and Symbol columns. (we have already uploaded); Upload Transactions CSV. Missing columns: Price (we have already upladed)"
2. **Feature Request:** "can you add definitions (alpha, any calculations done); why peak return is not there for all stocks; Could not auto-detect Symbol or P/L % column. Common names: 'Stock Symbol', 'Unrealized ProfitLoss %'. Column names above must match one of those exactly (case-insensitive).; buy heat map tool tip should show stock details that were bought"
3. **Clarification:** "what does the color gradiaent in the buy heat map reflect?"
4. **Refinement:** "perf heat map - Could not auto-detect Symbol or P/L % column. Common names: 'Stock Symbol', 'Unrealized ProfitLoss %'. Column names above must match one of those exactly (case-insensitive).; yes change the buy heat mat based on amount invested;"
5. **Bug Report:** "ValueError: Unknown format code 'f' for object of type 'str' ... P/L % column Unrealized Profit/Loss; realised profit is only there when there is both buy and sell in teh same stock"
6. **Bug Report:** "TypeError: Column 'Unrealized Profit/Loss %' has dtype object, cannot use method 'nlargest' with this dtype"

### Phase 2: Data Coercion & Chart Logic Fixes
7. **Bug Report & Feature Request:** "inflation override is not working, also the default cpi must be displayed int he same field; overview (allocation) does not display any stocks in read event thoguh we have ones which are in loss; perf heat maps does not show any loss making stocks;"
8. **Logic Correction:** "are you calculating the loss percentages or taking it from the data uploaded? they are all incorrect for e.g. brasol in th overview shows 2.3% loss but it is a 53.42%; you can directly use the values in the transactions.csv column (Unrealized Profit/Loss %)"
9. **Feature Request:** "for every element that is displayed create a json map of the field from the 2 files and display it under the settings and they should be editable; what is the basis for the pie chart?"
10. **Refinement:** "allocation pie chart should be based on contribution of the stock (by market value) to the overall current portfolio value"

### Phase 3: APIs & Data Quality
11. **API Inquiry:** "whata re these messgaes '1 Failed download: ['HINCOP.NS']: YFTzMissingError('possibly delisted; no timezone found')'"
12. **Bug Report:** "[Provided a traceback log relating to 'Unrealized ProfitLoss %' KeyErrors and DataFrame rendering issues]"
13. **Mapping Feature:** "remember the sotck symbol in the file is of a specific broker (icicicirect in this case) and may not always match the one in yfinance, you will need to intelligently map these symbols; where is the json file that maps the fields to the displayed elements across the app"
14. **Clarification:** "where are all the json files being stored?"
15. **Bug Report:** "i dont see this file ticker_map.json"
16. **Automation Request:** "Ticker Corrections should happen automatically when the csv files are uploaded"

### Phase 4: UI/UX Polish
17. **UI Tweaks & Feedback:** "title is cutoff '📈 Portfolio Dashboard'. I noticed that you seem to be making too many changes, make small scrips directedd changes"
18. **Layout Adjustments:** "the title istill cuthorizontally; additionally increase the space between two cards/widgets/sectiosn across all tabs"
19. **Chart Scaling Fix:** "look at the first 2 images the spacing is off; in the growth tab nifty is always 0"
20. **Final Touches:** "bottom table on the overview page has no title, check all tables and charts to ensure they have appropriate titles"
21. **Documentation:** "create a md file of all the prompts that i have used to create this project"
