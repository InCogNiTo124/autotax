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

import json

APP = typer.Typer()

ROOT = Path(__file__).parent.parent

with (ROOT / "codes.json").open() as f:
    CODES = json.load(f)

with (ROOT / "surtax.json").open() as f:
    SURTAX = json.load(f)

CAPITAL_INCOME_TAX = fractions.Fraction(20, 100)

# every place in surtax must appear in codes
# but not every place is assigned a surtax
assert SURTAX.keys() <= CODES.keys()

def conversion_rate_for_date(date: datetime):
    hnb_url = "https://api.hnb.hr/tecajn-eur/v3?datum-primjene={}&valuta=USD"
    response = requests.get(
        hnb_url.format(date.date().strftime('%Y-%m-%d'))
    ).json()[0]
    srednji_tecaj = response['srednji_tecaj']
    return fractions.Fraction(srednji_tecaj.replace(',', '.'))

def taxify(total_money, surtax_rate):
    bruto_raw = total_money / (1-CAPITAL_INCOME_TAX*(1+surtax_rate))
    bruto = round(bruto_raw, 2)
    tax = round(bruto*CAPITAL_INCOME_TAX, 2)
    surtax = round(tax*surtax_rate, 2)
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
    form_name_template = "ObrazacJOPPD_{oib}_{day:02}{month:02}{year:04}_{joppd_code}_8.xml"
    form_name = form_name_template.format(
            oib=oib,
            joppd_code=joppd_code,
            day=date.day,
            month=date.month,
            year=date.year)
    year_start = datetime(date.year, 1, 1, 0, 0, 0)
    year_end = datetime(date.year, 12, 31, 23, 59, 59)
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



def calculate_joppd_code(date):
    # last two characters of the year
    year = date.strftime('%y')
    day_of_year = date.strftime('%j')
    return f"{year}{day_of_year}"

@APP.command()
def main(
    first_name: Annotated[str, typer.Option(prompt=True)],
    last_name: Annotated[str, typer.Option(prompt=True)],
    oib: Annotated[str, typer.Option(prompt="OIB")],
    date: Annotated[datetime, typer.Option(prompt=True)],
    town: Annotated[str, typer.Option(prompt=True)],
    street_name: Annotated[str, typer.Option(prompt="Street name (without number)")],
    street_number: Annotated[int, typer.Option(prompt=True)],
    email_address: Annotated[str, typer.Option(prompt=True)],
    gsu_price_raw: Annotated[str, typer.Option(prompt="GSU price (USD)")],
    gsu_amount: Annotated[int, typer.Option(prompt="GSU amount")],
    ):
    town = town.lower()
    if town not in CODES:
        print(f'ERROR: town {town} does not exist. Exiting!')  # TODO add suggested towns
        raise typer.Exit(code=1)
    gsu_price = fractions.Fraction(gsu_price_raw)
    surtax_rate = fractions.Fraction(SURTAX[town], 100)
    typer.echo(f"Person: {first_name.capitalize()} {last_name.capitalize()}")
    typer.echo(f"        {street_name.capitalize()} {str(street_number)}, {town}")
    typer.echo(f"        {email_address}")
    typer.echo(f"        OIB: {oib}")
    typer.echo(f"surtax: {int(100*surtax_rate)}%")
    _ = typer.confirm('Does this look correct?', abort=True)
    typer.echo()
    joppd_code = calculate_joppd_code(date.date())
    conversion_rate = conversion_rate_for_date(date)
    total_money_usd = gsu_amount * gsu_price
    total_money_eur = round(total_money_usd / conversion_rate, 2)
    bruto, tax, surtax, neto = taxify(total_money_eur, surtax_rate)
    typer.echo(f"INFO: Code for {town}: {CODES[town]}")
    typer.echo(f"INFO: JOPPD code: {joppd_code}")
    typer.echo(f"INFO: Conversion rate ($ => €) @ {date.date().strftime('%Y-%m-%d')}: {float(conversion_rate)}")
    typer.echo(f"INFO: {gsu_amount} GSUs × {float(gsu_price)}$ = {float(total_money_usd)}$ = {float(total_money_eur)}€")
    typer.echo(f"INFO: bruto  = {float(bruto)}€")
    typer.echo(f"INFO: tax    = {float(tax)}€")
    typer.echo(f"INFO: surtax = {float(surtax)}€")
    typer.echo(f"INFO: neto   = {float(neto)}€")
    typer.echo(f"INFO: TOTAL COST (tax+surtax) = {float(tax+surtax)}€")
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
