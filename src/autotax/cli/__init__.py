# SPDX-FileCopyrightText: 2023-present InCogNiTo124 <msmetko@google.com>
#
# SPDX-License-Identifier: MIT
import typer
from typing import Annotated
from datetime import datetime
import fractions
import requests
import jinja2
import uuid
from pathlib import Path
import difflib

import json
import locale

# en_HR isn't widely available so en_DK is used instead.
locale.setlocale(locale.LC_NUMERIC, "en_DK.UTF-8")

APP = typer.Typer()

ROOT = Path(__file__).parent.parent

with (ROOT / "codes.json").open() as f:
    CODES = json.load(f)

with (ROOT / "tax_2024.json").open() as f:
    TAX_PER_TOWN = json.load(f)

# every place in surtax must appear in codes
# but not every place is assigned a surtax
# assert TAX_PER_TOWN.keys() <= CODES.keys()

def format_float(n: float) -> str:
    return locale.format_string("%.2f", n)

def check_oib(oib: str):
    """Check if OIB is valid and return True if it is."""
    OIB_LEN = 11
    
    if len(oib) != OIB_LEN or not oib.isdigit():
        return False

    medu_ostatak = 0
    for digit in oib[:-1]:
        medu_ostatak += int(digit)
        medu_ostatak %= 10
        if medu_ostatak == 0:
            medu_ostatak = 10
        medu_ostatak *= 2
        medu_ostatak %= 11

    kontrolni = OIB_LEN - medu_ostatak
    if kontrolni == 10:
        kontrolni = 0

    return kontrolni == int(oib[-1])

def conversion_rate_for_date(date: datetime):
    hnb_url = "https://api.hnb.hr/tecajn-eur/v3?datum-primjene={}&valuta=USD"
    response = requests.get(
        hnb_url.format(date.date().strftime('%Y-%m-%d'))
    ).json()[0]
    srednji_tecaj = response['srednji_tecaj']
    return fractions.Fraction(srednji_tecaj.replace(',', '.'))

def taxify(total_money, tax_rate):
    bruto_raw = total_money / (1-tax_rate)
    bruto = round(bruto_raw, 2)
    tax = round(bruto*tax_rate, 2)
    surtax = fractions.Fraction(0)
    neto = bruto - tax - surtax
    return bruto, tax, surtax, neto

def generate_joppd(*,
    first_name: str,
    last_name: str,
    date: datetime,
    joppd_code: str,
    town: str,
    street_name: str,
    email_address: str,
    oib: str,
    tax: fractions.Fraction,
    surtax: fractions.Fraction,
    bruto: fractions.Fraction,
    neto: fractions.Fraction,
    street_number: int
    ):
    print(date)
    form_name_template = "ObrazacJOPPD_{oib}_{day:02}{month:02}{year:04}_{joppd_code}_8.xml"
    form_name = form_name_template.format(
            oib=oib,
            joppd_code=joppd_code,
            day=date.day,
            month=date.month,
            year=date.year)
    year_start = datetime(date.year, 1, 1, 0, 0, 0)
    year_end = datetime(date.year, 12, 31, 23, 59, 59)
    print('ok', date, year_start, year_end)
    env = jinja2.Environment()
    template = env.from_string((ROOT / 'joppd_template.j2').read_text())
    rendered = template.render(
        first_name=first_name,
        last_name=last_name,
        now=datetime.now(),
        document_id=str(uuid.uuid4()),
        date_string=date,
        joppd_code=joppd_code,
        street_number=street_number,
        town=town,
        street_name=street_name,
        email=email_address,
        oib=oib,
        tax=tax,
        surtax=surtax,
        city_code=CODES[town],
        year_first_day=year_start,
        year_last_day=year_end,
        bruto=bruto,
        neto=neto
    )

    with open(form_name, 'w') as f:
        f.write(rendered)

    return form_name

def format_did_you_mean(candidates):
    if len(candidates) == 1:
        return f'"{candidates[0]}"'
    return ', '.join(f'"{s}"' for s in candidates[:-1]) + f' or "{candidates[-1]}"'

def calculate_joppd_code(date):
    # last two characters of the year
    year = date.strftime('%y')
    day_of_year = date.strftime('%j')
    return f"{year}{day_of_year}"

def town_callback(_a, _b, value: str) -> str:
    if value.lower() not in CODES.keys():
        candidates = difflib.get_close_matches(value, list(CODES.keys()))
        dym = format_did_you_mean(candidates)
        raise typer.BadParameter(f"Wrong value '{value}' - did you mean {dym}?")
    return value

def oib_callback(_a, _b, value: str) -> str:
    if not check_oib(value):
        raise typer.BadParameter(f"OIB '{value}' does not pass validity checks. Try again.")
    return value

@APP.command()
def main(
    first_name: Annotated[str, typer.Option(prompt=True)],
    last_name: Annotated[str, typer.Option(prompt=True)],
    oib: Annotated[str, typer.Option(prompt="OIB", callback=oib_callback)],
    date: Annotated[datetime, typer.Option(prompt=True)],
    town: Annotated[str, typer.Option(prompt=True, callback=town_callback)],
    street_name: Annotated[str, typer.Option(prompt="Street name (without number)")],
    street_number: Annotated[int, typer.Option(prompt=True)],
    email_address: Annotated[str, typer.Option(prompt=True)],
    gsu_price_raw: Annotated[str, typer.Option(prompt="GSU price (USD)")],
    gsu_amount: Annotated[int, typer.Option(prompt="GSU amount")],
    ):
    town = town.lower()
    if town not in CODES:
        print(f'ERROR: town {town} does not exist. Exiting!')
        raise typer.Exit(code=1)
    gsu_price = fractions.Fraction(gsu_price_raw)
    tax_rate = fractions.Fraction.from_decimal(fractions.Decimal.from_float(TAX_PER_TOWN[town])) / 100
    typer.echo(f"Person: {first_name.capitalize()} {last_name.capitalize()}")
    typer.echo(f"        {street_name.capitalize()} {str(street_number)}, {town}")
    typer.echo(f"        {email_address}")
    typer.echo(f"        OIB: {oib}")
    typer.echo(f"tax:    {int(100*tax_rate)}%")
    _ = typer.confirm('Does this look correct?', abort=True)
    typer.echo()
    joppd_code = calculate_joppd_code(date.date())
    conversion_rate = conversion_rate_for_date(date)
    total_money_usd = gsu_amount * gsu_price
    total_money_eur = round(total_money_usd / conversion_rate, 2)
    bruto, tax, surtax, neto = taxify(total_money_eur, tax_rate)
    typer.echo(f"INFO: Code for {town}: {CODES[town]}")
    typer.echo(f"INFO: JOPPD code: {joppd_code}")
    typer.echo(f"INFO: Conversion rate (€ => $) @ {date.date().strftime('%Y-%m-%d')}: {format_float(float(conversion_rate))}")
    typer.echo(f"INFO: {gsu_amount} GSUs × {format_float(float(gsu_price))}$ = {format_float(float(total_money_usd))}$ = {format_float(float(total_money_eur))}€")
    typer.echo(f"INFO: bruto  = {format_float(float(bruto))}€")
    typer.echo(f"INFO: tax    = {format_float(float(tax))}€")
    typer.echo(f"INFO: neto   = {format_float(float(neto))}€")
    typer.echo(f"INFO: TOTAL COST (tax) = {format_float(float(tax))}€")
    if typer.confirm("Do you want to generate JOPPD?", default=True):
        filename = generate_joppd(
                first_name=first_name,
                last_name=last_name,
                oib=oib,
                street_name=street_name,
                street_number=street_number,
                town=town,
                bruto=bruto,
                neto=neto,
                tax=tax,
                surtax=surtax,
                joppd_code=joppd_code,
                date=date,
                email_address=email_address,
        )
        typer.echo(f"JOPPD generated as {filename}")
    else:
        print('ok then, have fun lol')
    return

if __name__ == "__main__":
    APP()
